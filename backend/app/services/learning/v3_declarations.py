# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/v3_declarations.py
# @brief      Sprint 4b V3 J4 — declarations a V3 tool MUST attach to its
#             @register decorator, plus the gates that validate them.
#
#             Three kwargs introduced for V3 tools (alongside the existing
#             V2 metadata like skill_name / domain / skill_description):
#
#               - network_allow   = ["api.openweathermap.org", ".github.com"]
#                 Domains the tool may reach. Must be a subset of the
#                 egress-proxy's Squid ACL (otherwise the proxy refuses at
#                 runtime — we surface that mismatch at validation time).
#
#               - requires        = ["httpx", "beautifulsoup4"]
#                 Python distribution names the tool needs. Must be a subset
#                 of the libs baked into the sandbox image (see
#                 sandbox/requirements.txt). Bumping = PR to that file +
#                 BAKED_LIBS here in lockstep.
#
#               - requires_secrets = ["openweather_api_key"]
#                 Vault label(s) the runtime will inject as env vars to the
#                 sandbox. The plaintext NEVER appears in the tool source.
#
#             This module ONLY ships the parser + the three checkers. The
#             integration into the validation pipeline (calling them after
#             code_guard when profile=="io") lands in J5 — keeping J4 a
#             reviewable brick.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)


# ── Baked-libs allow-list ────────────────────────────────────────────────────
# Distribution names of the libs ACTUALLY installed in the sandbox image
# (sandbox/requirements.txt). A `requires=[...]` declaration must be a SUBSET
# of this — otherwise the tool imports something that won't resolve at
# runtime. The pin test below asserts these two lists stay in lockstep on
# every PR; if you bump one, the test forces you to bump the other.
BAKED_LIBS: Final[frozenset[str]] = frozenset({
    "httpx",
    "beautifulsoup4",
    "lxml",
})

_REQUIREMENTS_PATH = Path(__file__).resolve().parents[3].parent / "sandbox" / "requirements.txt"
_SQUID_CONF_PATH = Path(__file__).resolve().parents[3].parent / "sandbox" / "squid" / "squid.conf"


def squid_allowed_domains() -> list[str]:
    """Domaines autorisés par l'ACL egress de la sandbox (J7, v1.16.0).

    Parse la ligne ``acl allowed_domains dstdomain .a.tld .b.tld`` de
    ``sandbox/squid/squid.conf`` — la même source de vérité que le proxy au
    runtime. Retourne ``[]`` si le fichier est illisible (le prompt du
    générateur dégrade en avertissement explicite plutôt qu'en liste
    inventée).
    """
    try:
        for line in _SQUID_CONF_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("acl allowed_domains dstdomain"):
                return stripped.split()[3:]
    except Exception as exc:  # noqa: BLE001
        logger.warning("squid_allowed_domains: %s illisible (%s)", _SQUID_CONF_PATH, exc)
    return []


# ── Validation regexes ───────────────────────────────────────────────────────
# Domain: lowercase letters/digits/hyphens, dot-separated, optional leading
# dot (Squid's `.example.com` suffix-match form is the canonical wire form).
# Strict on purpose: no IPs, no wildcards beyond the leading dot, no ports.
_DOMAIN_RE: Final[re.Pattern] = re.compile(
    r"^\.?(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)

# Vault secret label: snake_case alphanumeric. Same shape the Vault UI lets
# the user create (lowercase letter first, then [a-z0-9_]).
_LABEL_RE: Final[re.Pattern] = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


# ── Result types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class V3Declarations:
    """The three lists, parsed (always present as lists — empty means the
    tool didn't declare anything in that category)."""

    network_allow: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    requires_secrets: tuple[str, ...] = ()

    @property
    def is_pure(self) -> bool:
        """True iff the tool declared no network access, no extra libs, no
        secrets — i.e. it's a V2 pure tool that happens to be checked under
        the V3 lens. Useful for the orchestrator to short-circuit V3 gates
        (skipping them is legitimate, not a bug)."""
        return not (self.network_allow or self.requires or self.requires_secrets)


@dataclass(frozen=True)
class DeclarationsReport:
    """Result of one of the gates below."""

    ok: bool
    violations: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        if self.ok:
            return "ok"
        return "; ".join(self.violations)


# ── Parsing ──────────────────────────────────────────────────────────────────


_REGISTER_DECORATOR_NAMES: Final[frozenset[str]] = frozenset({"register"})


def _parse_string_list(node: ast.AST) -> list[str] | None:
    """Return the list of string constants in ``node`` if it's an ``ast.List``
    whose elements are all string constants ; ``None`` otherwise. Catches the
    sneaky cases (set literal, tuple, list with a non-string entry, etc.) so
    the well-formed gate can give a precise message."""
    if not isinstance(node, ast.List):
        return None
    out: list[str] = []
    for elt in node.elts:
        if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
            return None
        out.append(elt.value)
    return out


def parse_v3_declarations(source: str) -> V3Declarations:
    """Parse the V3 declarations from ``@register(...)``.

    Tolerant: returns empty declarations for any source that doesn't parse,
    lacks ``@register``, or doesn't declare these particular kwargs. The
    well-formed gate is what TURNS a malformed declaration into a failure
    — extraction itself never raises.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return V3Declarations()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name)):
                continue
            if dec.func.id not in _REGISTER_DECORATOR_NAMES:
                continue
            kwargs: dict[str, list[str]] = {}
            for kw in dec.keywords:
                if kw.arg not in {"network_allow", "requires", "requires_secrets"}:
                    continue
                parsed = _parse_string_list(kw.value)
                # ``None`` here means the kwarg is present but malformed
                # (not a list of strings). We carry it through as an empty
                # list — the well-formed gate will flag it via the
                # ``_declared_but_malformed`` audit below.
                kwargs.setdefault(kw.arg + "__malformed", [])
                if parsed is None:
                    kwargs[kw.arg + "__malformed"] = ["non-string-list"]
                    kwargs[kw.arg] = []
                else:
                    kwargs[kw.arg] = parsed
            return V3Declarations(
                network_allow=tuple(kwargs.get("network_allow", [])),
                requires=tuple(kwargs.get("requires", [])),
                requires_secrets=tuple(kwargs.get("requires_secrets", [])),
            )
    return V3Declarations()


def _declared_but_malformed(source: str) -> dict[str, bool]:
    """Helper for the well-formed gate: returns a {field: True} dict for any
    V3 kwarg that was PRESENT in @register but couldn't be parsed as a list
    of strings. Lets us distinguish "not declared" from "declared wrong"."""
    out: dict[str, bool] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name)):
                continue
            if dec.func.id not in _REGISTER_DECORATOR_NAMES:
                continue
            for kw in dec.keywords:
                if kw.arg not in {"network_allow", "requires", "requires_secrets"}:
                    continue
                if _parse_string_list(kw.value) is None:
                    out[kw.arg] = True
            return out
    return out


# ── Gate 1: declarations well-formed ─────────────────────────────────────────


def check_declarations_wellformed(
    source: str,
    decls: V3Declarations | None = None,
) -> DeclarationsReport:
    """Static check: each V3 declaration is a well-formed list of valid
    strings, no duplicates, no empty entries, domains match the canonical
    form, secret labels match the canonical form.

    Pass ``decls`` if you've already parsed it — saves a re-parse.
    """
    decls = decls if decls is not None else parse_v3_declarations(source)
    malformed = _declared_but_malformed(source)
    violations: list[str] = []

    if malformed:
        for k in sorted(malformed):
            violations.append(
                f"{k}: must be a list of string literals (got something else)"
            )

    def _check_list(field_name: str, values: tuple[str, ...], pattern: re.Pattern,
                    human: str, extra_check=None) -> None:
        seen: set[str] = set()
        for i, v in enumerate(values):
            if not isinstance(v, str) or not v:
                violations.append(f"{field_name}[{i}]: empty or non-string entry")
                continue
            if v in seen:
                violations.append(f"{field_name}: duplicate entry {v!r}")
            seen.add(v)
            if not pattern.match(v):
                violations.append(f"{field_name}[{i}]: {human} {v!r}")
                continue
            if extra_check is not None:
                msg = extra_check(v)
                if msg:
                    violations.append(f"{field_name}[{i}]: {msg} {v!r}")

    def _not_an_ipv4(v: str) -> str | None:
        # Domain regex accepts any digit-only label, which means 192.168.1.1
        # passes structurally. Reject anything with no letter anywhere — it's
        # an IP literal (or close enough). The egress-proxy filters by
        # dstdomain, IP literals can't be authorised that way anyway.
        if not any(c.isalpha() for c in v):
            return "must be a domain name (IP literals not supported by dstdomain ACLs)"
        return None

    _check_list("network_allow", decls.network_allow, _DOMAIN_RE,
                "not a valid domain", extra_check=_not_an_ipv4)
    _check_list("requires_secrets", decls.requires_secrets, _LABEL_RE,
                "not a valid vault label (lowercase, snake_case, [a-z][a-z0-9_]{2,63})")

    # `requires` doesn't have a regex — the subset-of-baked gate is what
    # validates it. But we still check for the structural defects.
    seen: set[str] = set()
    for i, v in enumerate(decls.requires):
        if not isinstance(v, str) or not v:
            violations.append(f"requires[{i}]: empty or non-string entry")
            continue
        if v in seen:
            violations.append(f"requires: duplicate entry {v!r}")
        seen.add(v)

    return DeclarationsReport(ok=not violations, violations=tuple(violations))


# ── Gate 2: requires ⊆ BAKED_LIBS ────────────────────────────────────────────


def check_deps_subset_of_baked(
    decls: V3Declarations,
    *,
    baked: frozenset[str] = BAKED_LIBS,
) -> DeclarationsReport:
    """Every entry in ``decls.requires`` must be installed in the sandbox
    image. We can't ``pip install`` at runtime (no pip in the system Python
    — see sandbox/Dockerfile), so an unknown dep would fail at import."""
    extras = [r for r in decls.requires if r not in baked]
    if not extras:
        return DeclarationsReport(ok=True)
    return DeclarationsReport(
        ok=False,
        violations=tuple(
            f"requires: {r!r} is not in the sandbox image — "
            f"add it to sandbox/requirements.txt (and BAKED_LIBS) in a PR first"
            for r in extras
        ),
    )


# ── Gate 3: every label in requires_secrets exists in the user's Vault ───────


async def check_secrets_exist(
    decls: V3Declarations,
    user_id: str,
    *,
    vault_service: object | None = None,
) -> DeclarationsReport:
    """Best-effort check that each declared Vault label is provisioned for
    ``user_id``. Returns a CLEAR violation message listing the missing
    labels, never raises — a Vault hiccup degrades to "ok with no labels"
    so the validation pipeline can still move forward (the runtime will
    re-check anyway when the sandbox actually asks for the secret).
    """
    if not decls.requires_secrets:
        return DeclarationsReport(ok=True)
    if not user_id:
        return DeclarationsReport(
            ok=False,
            violations=("requires_secrets: no user_id provided to look up Vault labels",),
        )

    if vault_service is None:
        try:
            from app.services.vault_service import get_vault_service
            vault_service = get_vault_service()
        except Exception as exc:  # noqa: BLE001
            logger.warning("check_secrets_exist: vault service unreachable (%s)", exc)
            return DeclarationsReport(ok=True)  # degrade open — runtime will catch

    try:
        entries = await vault_service.list_secrets(user_id)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        logger.warning("check_secrets_exist: list_secrets failed (%s)", exc)
        return DeclarationsReport(ok=True)  # degrade open

    available = {(e.get("label") if isinstance(e, dict) else getattr(e, "label", None)) for e in entries}
    missing = [s for s in decls.requires_secrets if s not in available]
    if not missing:
        return DeclarationsReport(ok=True)
    return DeclarationsReport(
        ok=False,
        violations=tuple(
            f"requires_secrets: label {label!r} is not in user's Vault — "
            f"the user must store it before this tool can run"
            for label in missing
        ),
    )


# ── Lockstep audit: BAKED_LIBS == sandbox/requirements.txt ───────────────────


def _read_requirements_distribution_names() -> set[str]:
    """Parse sandbox/requirements.txt and return the set of distribution
    names (just the package, no version pin, no extras). Used by the pin
    test below; kept in the module so other call-sites can audit too."""
    if not _REQUIREMENTS_PATH.is_file():
        return set()
    names: set[str] = set()
    for line in _REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # name[==<version>] — strip the version pin and any extras
        name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip()
        if name:
            names.add(name)
    return names
