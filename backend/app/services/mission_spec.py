# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_spec.py
# @brief      Sprint 4c J1 — format de mission structurée V2 : schéma,
#             parser YAML et validation (erreurs en français, exhaustives).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Structured mission spec — the Sprint 4c contract.

Le problème (backlog 2026-06-09) : les missions multi-étapes reposaient sur
UN prompt monolithe « long comme le bras ». Oublier un cas de figure (nom
ambigu, entreprise introuvable, boîte en redressement…) = réécrire le
prompt entier et re-tester. La spec structurée remplace ce monolithe :

- ``steps`` ordonnés, chacun avec son instruction ``do`` (du langage
  naturel — le LLM reste dans la boucle, on CADRE l'exécution, on ne la
  remplace pas par un moteur déterministe) ;
- ``foreach`` pour itérer sur le résultat d'un step précédent ;
- des handlers d'edge-case par step (``on_ambiguous``, ``on_not_found``,
  ``on_error``, ``on_<n'importe_quel_cas>``) dont les actions sont un petit
  vocabulaire fermé — **ajouter un cas oublié = ajouter UNE ligne**, pas
  réécrire le prompt ;
- ``ask_user(...)`` est LE cœur de la valeur : la mission qui hésite pose
  la question (HITL réutilisé), l'utilisateur répond, la mission reprend —
  le « mode chat fait à la main » de Franck, automatisé.

Exemple canonique (prospection) ::

    version: 1
    steps:
      - id: read_companies
        do: "Lis les noms d'entreprises du Google Sheet « Prospection »."

      - id: enrich_company
        foreach: "{{ read_companies.output }}"
        do: |
          Trouve le dirigeant de {{ item }} sur LinkedIn et récupère
          nom + email professionnel.
        on_ambiguous: ask_user("Plusieurs résultats pour {{ item }} — lequel ?")
        on_not_found: skip_with_note("Entreprise introuvable")
        on_in_liquidation: ask_user("{{ item }} est en redressement — continuer ?")
        on_error: resume_next

Ce module est VOLONTAIREMENT autonome (pas d'import DB/agent) : J1 livre le
contrat + le parser ; l'exécuteur (J2), le hook ask_user (J3) et le viewer
(J4) le consomment. La validation collecte TOUTES les erreurs (pas de
fail-fast) avec le contexte du step — l'utilisateur corrige tout en une
passe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

import yaml

# ── Contraintes du format ────────────────────────────────────────────────────

SPEC_VERSION: Final[int] = 1
MAX_STEPS: Final[int] = 50

_ID_RE: Final[re.Pattern] = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Référence au résultat d'un step : {{ <step_id>.output }}
_FOREACH_REF_RE: Final[re.Pattern] = re.compile(
    r"^\{\{\s*([a-z][a-z0-9_]{0,63})\.output\s*\}\}$"
)
# Sucre compact pour les handlers : action("argument") ou action
_HANDLER_SUGAR_RE: Final[re.Pattern] = re.compile(
    r"""^([a-z][a-z0-9_]*)\s*(?:\(\s*(?:"([^"]*)"|'([^']*)')?\s*\))?$"""
)

# Vocabulaire fermé des actions de handler (V1). Chaque entrée précise si un
# argument texte est requis / accepté. Fermé À DESSEIN : un vocabulaire
# extensible par l'utilisateur redeviendrait un moteur de workflow.
HANDLER_ACTIONS: Final[dict[str, dict[str, bool]]] = {
    # La mission s'interrompt sur ce step/item, pose la question via HITL,
    # reprend à la réponse. LE cœur du Sprint 4c.
    "ask_user": {"arg_required": True},
    # L'item/step est sauté, la note apparaît dans le viewer.
    "skip_with_note": {"arg_required": True},
    # On journalise et on passe à l'item/step suivant (défaut de on_error).
    "resume_next": {"arg_required": False},
    # Échec franc de la mission, avec message.
    "fail": {"arg_required": False},
}


# ── Modèle ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HandlerCall:
    """Une action de handler parsée : ``ask_user("…")`` → action + message."""

    action: str
    message: str | None = None


@dataclass(frozen=True)
class SpecStep:
    id: str
    do: str
    foreach: str | None = None
    # Clé = nom du cas SANS le préfixe on_ (ex. "ambiguous", "error",
    # "in_liquidation"). Libre : les edge-cases sont métier par nature.
    handlers: dict[str, HandlerCall] = field(default_factory=dict)

    @property
    def foreach_ref(self) -> str | None:
        """Step id référencé par ``foreach`` quand il utilise la forme
        ``{{ step.output }}`` ; None pour la forme texte libre (interprétée
        par le LLM à l'exécution)."""
        if not self.foreach:
            return None
        m = _FOREACH_REF_RE.match(self.foreach.strip())
        return m.group(1) if m else None


@dataclass(frozen=True)
class MissionSpec:
    version: int
    steps: tuple[SpecStep, ...]

    def step_ids(self) -> list[str]:
        return [s.id for s in self.steps]


class MissionSpecError(ValueError):
    """Toutes les erreurs de la spec, en une passe, en français."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


# ── Parsing des handlers ─────────────────────────────────────────────────────


def _parse_handler_value(raw: Any, where: str, errors: list[str]) -> HandlerCall | None:
    """Accepte le sucre string ``action("msg")`` OU la forme mapping
    ``{action: ask_user, message: "…"}``."""
    action: str | None = None
    message: str | None = None

    if isinstance(raw, str):
        m = _HANDLER_SUGAR_RE.match(raw.strip())
        if not m:
            errors.append(
                f"{where} : forme invalide {raw!r} — attendu "
                f"action(\"message\") ou action ({', '.join(sorted(HANDLER_ACTIONS))})"
            )
            return None
        action = m.group(1)
        message = m.group(2) if m.group(2) is not None else m.group(3)
    elif isinstance(raw, dict):
        action = raw.get("action")
        message = raw.get("message")
        if not isinstance(action, str):
            errors.append(f"{where} : la forme mapping exige une clé 'action'")
            return None
        if message is not None and not isinstance(message, str):
            errors.append(f"{where} : 'message' doit être une chaîne")
            return None
        unknown_keys = set(raw) - {"action", "message"}
        if unknown_keys:
            errors.append(
                f"{where} : clé(s) inconnue(s) {sorted(unknown_keys)} — "
                f"seules 'action' et 'message' sont acceptées"
            )
    else:
        errors.append(f"{where} : doit être une chaîne ou un mapping, pas {type(raw).__name__}")
        return None

    spec = HANDLER_ACTIONS.get(action or "")
    if spec is None:
        errors.append(
            f"{where} : action inconnue {action!r} — actions disponibles : "
            f"{', '.join(sorted(HANDLER_ACTIONS))}"
        )
        return None
    if spec["arg_required"] and not (message or "").strip():
        errors.append(f"{where} : {action} exige un message (ex. {action}(\"…\"))")
        return None
    return HandlerCall(action=action, message=(message or None))


# ── Parser principal ─────────────────────────────────────────────────────────


def parse_mission_spec(text: str) -> MissionSpec:
    """Parse + valide une spec YAML. Lève :class:`MissionSpecError` avec
    TOUTES les erreurs (l'utilisateur corrige en une passe)."""
    errors: list[str] = []

    try:
        data = yaml.safe_load(text or "")
    except yaml.YAMLError as exc:
        raise MissionSpecError([f"YAML invalide : {exc}"]) from exc

    if not isinstance(data, dict):
        raise MissionSpecError(
            ["la spec doit être un document YAML avec les clés 'version' et 'steps'"]
        )

    version = data.get("version")
    if version != SPEC_VERSION:
        errors.append(
            f"version : {version!r} non supportée — seule la version "
            f"{SPEC_VERSION} existe"
        )

    unknown_top = set(data) - {"version", "steps"}
    if unknown_top:
        errors.append(
            f"clé(s) de premier niveau inconnue(s) : {sorted(unknown_top)} — "
            f"seules 'version' et 'steps' sont acceptées"
        )

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise MissionSpecError(
            errors + ["steps : liste non vide requise (au moins un step)"]
        )
    if len(raw_steps) > MAX_STEPS:
        errors.append(f"steps : {len(raw_steps)} steps — maximum {MAX_STEPS}")

    steps: list[SpecStep] = []
    seen_ids: set[str] = set()

    for idx, raw in enumerate(raw_steps, start=1):
        where = f"step {idx}"
        if not isinstance(raw, dict):
            errors.append(f"{where} : doit être un mapping (id/do/…)")
            continue

        step_id = raw.get("id")
        if not isinstance(step_id, str) or not _ID_RE.match(step_id):
            errors.append(
                f"{where} : 'id' requis, en snake_case ([a-z][a-z0-9_]*) — "
                f"reçu {step_id!r}"
            )
            step_id = None
        elif step_id in seen_ids:
            errors.append(f"{where} : id {step_id!r} déjà utilisé — les ids sont uniques")
            step_id = None
        if step_id:
            seen_ids.add(step_id)
            where = f"step {idx} ({step_id})"

        do = raw.get("do")
        if not isinstance(do, str) or not do.strip():
            errors.append(f"{where} : 'do' requis — l'instruction du step en langage naturel")
            do = ""

        foreach = raw.get("foreach")
        if foreach is not None and (not isinstance(foreach, str) or not foreach.strip()):
            errors.append(f"{where} : 'foreach' doit être une chaîne non vide")
            foreach = None

        handlers: dict[str, HandlerCall] = {}
        known_keys = {"id", "do", "foreach"}
        for key, value in raw.items():
            if key in known_keys:
                continue
            if not (isinstance(key, str) and key.startswith("on_") and len(key) > 3):
                errors.append(
                    f"{where} : clé inconnue {key!r} — un handler d'edge-case "
                    f"commence par on_ (ex. on_ambiguous, on_not_found)"
                )
                continue
            call = _parse_handler_value(value, f"{where} → {key}", errors)
            if call is not None:
                handlers[key[3:]] = call

        steps.append(SpecStep(
            id=step_id or f"_invalid_{idx}",
            do=(do or "").strip(),
            foreach=(foreach or None) and foreach.strip(),
            handlers=handlers,
        ))

    # ── Cohérence inter-steps : les références foreach pointent en ARRIÈRE ──
    for idx, step in enumerate(steps):
        ref = step.foreach_ref
        if ref is None:
            continue
        earlier = {s.id for s in steps[:idx]}
        if ref not in earlier:
            errors.append(
                f"step {idx + 1} ({step.id}) : foreach référence "
                f"'{{{{ {ref}.output }}}}' qui n'est pas un step PRÉCÉDENT "
                f"(steps disponibles : {sorted(earlier) or 'aucun'})"
            )

    if errors:
        raise MissionSpecError(errors)

    return MissionSpec(version=SPEC_VERSION, steps=tuple(steps))


def validate_mission_spec(text: str) -> list[str]:
    """Variante non levante pour les endpoints : [] si valide, sinon la
    liste des erreurs."""
    try:
        parse_mission_spec(text)
        return []
    except MissionSpecError as exc:
        return exc.errors
