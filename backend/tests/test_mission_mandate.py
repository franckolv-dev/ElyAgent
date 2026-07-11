# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_mandate.py
# @brief      Missions autonomes J1 — contrat du mandat : spec v2 `mandate:`,
#             gate flag, colonnes mandate_json/autonomy_state, migration 0018.
# @license    Elastic License 2.0
# =============================================================================
"""Missions autonomes J1 — pins du contrat de mandat.

Cadrage : docs_internes/cadrage_missions_autonomes.md (décisions D1→D6).
Principe : déplacer le HITL de l'action vers le mandat. J1 ne livre QUE le
contrat + le stockage — l'enforcement (J2), les disjoncteurs (J3), le
workspace (J4), le mode strict (J5) et l'UI (J6) suivent.
"""
from __future__ import annotations

import textwrap
import uuid

import pytest

# Le cas canonique du cadrage (chaîne YouTube) — si CE document ne parse
# pas, le jalon rate sa cible.
_CANONICAL_V2 = textwrap.dedent("""
    version: 2
    mandate:
      autonomy: autonomous
      tools_allow: [youtube, drive, files, web]
      on_unforeseen: escalate
      budgets:
        daily_tool_actions_notify: 500
        daily_llm_calls_notify: 100
    steps:
      - id: plan_contenu
        do: "Établis le planning éditorial de la semaine pour la chaîne."
      - id: produire
        foreach: "{{ plan_contenu.output }}"
        do: "Produis et publie la vidéo {{ item }}."
        on_error: resume_next
""").strip()

_V1_CANONICAL = textwrap.dedent("""
    version: 1
    steps:
      - id: lire
        do: "Lis le fichier clients.csv."
""").strip()


# ─────────────────────────────────────────────────────────────────────────
# Parser — chemin nominal v2
# ─────────────────────────────────────────────────────────────────────────


def test_canonical_v2_mandate_parses() -> None:
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(_CANONICAL_V2)

    assert spec.version == 2
    assert spec.mandate is not None
    assert spec.mandate.autonomy == "autonomous"
    assert spec.mandate.tools_allow == ("youtube", "drive", "files", "web")
    assert spec.mandate.on_unforeseen == "escalate"
    assert spec.mandate.llm_tier is None          # D3 : null ⇒ COMPLEX forcé (J2)
    assert spec.mandate.budgets.daily_tool_actions_notify == 500
    assert spec.mandate.budgets.daily_llm_calls_notify == 100
    assert spec.step_ids() == ["plan_contenu", "produire"]


def test_v2_mandate_defaults_applied() -> None:
    """Mandat minimal : seul tools_allow est requis, le reste a des défauts."""
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(textwrap.dedent("""
        version: 2
        mandate:
          tools_allow: [email]
        steps:
          - id: s1
            do: "x"
    """).strip())

    m = spec.mandate
    assert m is not None
    assert m.autonomy == "autonomous"
    assert m.on_unforeseen == "escalate"          # D2 : escalade par défaut
    assert m.llm_tier is None
    assert m.budgets.daily_tool_actions_notify == 500   # D4
    assert m.budgets.daily_llm_calls_notify == 100      # D4


def test_v2_without_mandate_is_valid_and_v1_intact() -> None:
    """v2 sans mandat = v1 + rien ; v1 strictement inchangée (rétrocompat)."""
    from app.services.mission_spec import parse_mission_spec

    v2 = parse_mission_spec("version: 2\nsteps:\n  - id: s1\n    do: x")
    assert v2.version == 2 and v2.mandate is None

    v1 = parse_mission_spec(_V1_CANONICAL)
    assert v1.version == 1 and v1.mandate is None


# ─────────────────────────────────────────────────────────────────────────
# Parser — refus exhaustifs (erreurs FR, une passe)
# ─────────────────────────────────────────────────────────────────────────


def test_mandate_requires_version_2() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec(textwrap.dedent("""
            version: 1
            mandate:
              tools_allow: [email]
            steps:
              - id: s1
                do: "x"
        """).strip())
    assert any("version: 2" in e for e in exc.value.errors)


def test_mandate_all_errors_collected_in_one_pass() -> None:
    """Le style maison : TOUTES les erreurs remontent d'un coup."""
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec(textwrap.dedent("""
            version: 2
            mandate:
              autonomy: yolo
              tools_allow: [ssh, chimère, email, email]
              on_unforeseen: improvise
              llm_tier: quantique
              budgets:
                daily_tool_actions_notify: -3
                inconnu: 1
            steps:
              - id: s1
                do: "x"
        """).strip())

    errs = "\n".join(exc.value.errors)
    assert "autonomy" in errs                 # valeur inconnue
    assert "INTERDITE" in errs                # ssh = noyau protégé (D1)
    assert "chimère" in errs                  # famille inconnue
    assert "double" in errs                   # email répété
    assert "on_unforeseen" in errs            # improvise ∉ {escalate, decide}
    assert "llm_tier" in errs                 # quantique ∉ {simple, medium, complex}
    assert "daily_tool_actions_notify" in errs  # entier ≥ 1 requis
    assert "inconnu" in errs                  # clé budgets inconnue


def test_mandate_tools_allow_required() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec(textwrap.dedent("""
            version: 2
            mandate:
              autonomy: autonomous
            steps:
              - id: s1
                do: "x"
        """).strip())
    assert any("tools_allow" in e for e in exc.value.errors)


def test_mandate_unknown_keys_rejected() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec(textwrap.dedent("""
            version: 2
            mandate:
              tools_allow: [email]
              pouvoir_illimite: true
            steps:
              - id: s1
                do: "x"
        """).strip())
    assert any("pouvoir_illimite" in e for e in exc.value.errors)


def test_unknown_version_still_rejected() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec("version: 3\nsteps:\n  - id: s1\n    do: x")
    assert any("version" in e for e in exc.value.errors)
