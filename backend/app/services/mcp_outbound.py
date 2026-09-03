# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_outbound.py
# @brief      Politique de données sortantes pour les appels MCP.
# @license    MIT
# =============================================================================
"""Un appel MCP = une SORTIE de données vers un tiers (cadrage §11.3).

Avant de transmettre des arguments à un serveur MCP, on les inspecte :

* **Secrets** (clés API, tokens, clés privées) → **bloqués** par défaut. Cas
  critique : ``tool_node`` résout les ``vault://label`` en clair AVANT l'appel ;
  sans ce filet, le modèle pourrait exfiltrer un secret du Vault en le plaçant
  dans un argument MCP. On bloque donc aussi toute référence ``vault://``
  résiduelle et toute valeur en forme de secret.
* **PII** (email, téléphone, IBAN, carte) → **signalées** (autorisées mais
  tracées ; l'anonymisation aveugle casserait l'outil, cf. cadrage §11.3).

Réutilise les motifs PII de la couche 1 (``security_filter``).
"""
from __future__ import annotations

import re
from typing import Any, NamedTuple

# Couche 1 — motifs PII existants (EMAIL/PHONE/IBAN/CARD/TOKEN).
from app.services.security_filter import _PATTERNS as _PII_PATTERNS

# Secrets « en forme de clé » de fournisseurs courants — bloqués fail-closed.
_SECRET_PATTERNS: dict[str, re.Pattern] = {
    "OPENAI_KEY":  re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "ANTHROPIC_KEY": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "GITHUB_TOKEN": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "AWS_KEY":     re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "SLACK_TOKEN": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "GOOGLE_KEY":  re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "JWT":         re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
}

# PII : signalée, pas bloquée (sauf TOKEN qui est un secret).
_PII_KINDS = ("EMAIL", "PHONE", "IBAN", "CARD")


class Finding(NamedTuple):
    kind: str
    field: str
    severity: str   # "secret" | "pii"


class OutboundVerdict(NamedTuple):
    allowed: bool
    reason: str | None
    findings: list[Finding]


def _iter_strings(value: Any, path: str = ""):
    """Parcourt récursivement toutes les chaînes d'une structure d'arguments."""
    if isinstance(value, str):
        yield path or "(racine)", value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _iter_strings(v, f"{path}[{i}]")


def scan_outbound(args: dict) -> list[Finding]:
    """Liste les secrets et PII détectés dans les arguments."""
    findings: list[Finding] = []
    for field, s in _iter_strings(args):
        if "vault://" in s:
            findings.append(Finding("VAULT_REF", field, "secret"))
        for kind, pat in _SECRET_PATTERNS.items():
            if pat.search(s):
                findings.append(Finding(kind, field, "secret"))
        # TOKEN générique de la couche 1 = secret.
        if _PII_PATTERNS["TOKEN"].search(s):
            findings.append(Finding("TOKEN", field, "secret"))
        for kind in _PII_KINDS:
            if _PII_PATTERNS[kind].search(s):
                findings.append(Finding(kind, field, "pii"))
    return findings


def enforce_outbound(args: dict) -> OutboundVerdict:
    """Décide si les arguments peuvent partir vers un serveur MCP tiers.

    Fail-closed sur les secrets ; PII autorisée mais tracée."""
    findings = scan_outbound(args)
    secrets = [f for f in findings if f.severity == "secret"]
    if secrets:
        kinds = ", ".join(sorted({f.kind for f in secrets}))
        fields = ", ".join(sorted({f.field for f in secrets}))
        return OutboundVerdict(
            allowed=False,
            reason=(
                f"⛔ Transmission bloquée : secret détecté ({kinds}) dans "
                f"l'argument(s) « {fields} ». Un serveur MCP tiers ne doit pas "
                f"recevoir de secret/credential. Retire-le ou utilise un serveur "
                f"de confiance avec un credential dédié côté Vault."
            ),
            findings=findings,
        )
    return OutboundVerdict(allowed=True, reason=None, findings=findings)
