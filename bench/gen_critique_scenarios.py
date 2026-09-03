#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/gen_critique_scenarios.py
# @brief      Sprint 3.7.3 J2 — generate the critique-replay scenario batch.
#
#             ORIGINAL J2 PLAN was to *mine* ~30 real `mission_critiques`
#             rows from the local DB. Reality check (2026-05-31): the table
#             is EMPTY in both the dev DB and the live prod DB (0 rows) —
#             the LLM-as-judge cron only started writing today (v1.11.1 fix)
#             and the instance has run 2 missions ever (usage is
#             conversational, not mission-driven). There is nothing to mine
#             and there never will be at scale on a personal instance.
#
#             So J2 pivots to SYNTHETIC critique-replay: a hand-curated
#             catalogue of ~30 representative critic verdicts, each emitted
#             as a self-contained `shallow` scenario that seeds a
#             Mission + MissionCritique and asserts the real downstream
#             pipeline — `capture_from_mission_critique` (actionability
#             filter + stable `pattern_hash`) and the learning-report
#             join `_load_mission_critiques`. No LLM, sub-second, honest
#             about being synthetic.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Generate (or list) the critique-replay canonical scenarios.

Usage (from the project root) ::

    # Dry-run (DEFAULT): print the catalogue plan, write nothing.
    python -m bench.gen_critique_scenarios

    # Actually emit the scenario_critique_*.py files.
    python -m bench.gen_critique_scenarios --write

    # Remove every generated scenario_critique_*.py file.
    python -m bench.gen_critique_scenarios --clean

The generated files are committed to git (the bench runner + CI discover
scenarios on disk), but they are AUTO-GENERATED — edit THIS catalogue and
re-run ``--write``, never hand-edit the output files.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


_HERE = Path(__file__).resolve().parent
_CANONICAL_DIR = _HERE / "scenarios" / "canonical"
_FILE_PREFIX = "scenario_critique_"


# ─────────────────────────────────────────────────────────────────────────
# Catalogue — 30 representative critic verdicts.
#
# Spread by design (verified by tests in test_bench_base.py):
#   • status : completed / failed / aborted
#   • quality_score : full 0–100 range, incl. the 59/60 capture boundary
#                     and the 30 fingerprint boundary (str(score < 30))
#   • honest_completion : both — incl. dishonest-high-score (captured)
#   • ~21 actionable (→ FailureCase) + ~9 non-actionable (→ skipped)
#
# `main_issue` strings are synthetic French one-liners with NO real PII;
# they're still passed through anonymise_text() defensively at seed time.
# ─────────────────────────────────────────────────────────────────────────
CATALOGUE: list[dict[str, Any]] = [
    # ── Façade success / dishonest completion (actionable) ──
    dict(slug="facade_success", status="completed", quality_score=20,
         honest_completion=False, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Envoyer le compte-rendu de réunion à l'équipe",
         main_issue="prétend avoir envoyé le mail mais aucun appel gmail_send_email dans la trace"),
    dict(slug="hallucinated_result", status="completed", quality_score=10,
         honest_completion=False, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Résumer le contenu du fichier trimestre.xlsx",
         main_issue="invente le contenu d'un fichier jamais ouvert avec drive_read_file"),
    dict(slug="partial_then_claimed_done", status="completed", quality_score=40,
         honest_completion=False, wasted_effort=True,
         user_should_have_been_warned=True, critic_model="mistral-large-3",
         tier_llm="C", prompt_version="benchv1",
         goal="Archiver les newsletters de la semaine",
         main_issue="a traité 3 mails sur 10 mais annonce la tâche entièrement terminée"),
    dict(slug="fabricated_citation", status="completed", quality_score=18,
         honest_completion=False, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Trouver les horaires d'ouverture de la mairie",
         main_issue="cite une source web jamais consultée par web_search"),
    dict(slug="silent_partial_failure", status="completed", quality_score=38,
         honest_completion=False, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="gemma-4-e4b-it",
         tier_llm="MAINTENANCE", prompt_version="benchv1",
         goal="Mettre à jour les trois feuilles du classeur budget",
         main_issue="une étape sheets_update a échoué silencieusement, non remontée à l'utilisateur"),
    dict(slug="dishonest_high_score", status="completed", quality_score=82,
         honest_completion=False, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv2",
         goal="Supprimer les doublons du Drive",
         main_issue="résultat correct en surface mais l'étape destructive drive_delete_file n'a pas été confirmée"),
    dict(slug="timeout_no_warning", status="failed", quality_score=24,
         honest_completion=False, wasted_effort=True,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Synchroniser le calendrier avec Doctolib",
         main_issue="timeout réseau présenté comme 'terminé' au lieu d'un échec"),
    dict(slug="wrong_recipient", status="completed", quality_score=30,
         honest_completion=False, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="mistral-large-3",
         tier_llm="C", prompt_version="benchv1",
         goal="Envoyer la facture au comptable",
         main_issue="mail envoyé au mauvais destinataire, divergence non signalée"),
    dict(slug="misread_eval", status="failed", quality_score=33,
         honest_completion=False, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="gemma-4-e4b-it",
         tier_llm="MAINTENANCE", prompt_version="benchv1",
         goal="Vérifier que la sauvegarde nocturne a réussi",
         main_issue="évalue 'succès' une étape dont le tool_output était une erreur 500"),

    # ── Wasted effort / loops / churn (actionable, honest) ──
    dict(slug="infinite_loop_drive", status="completed", quality_score=35,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=False, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Lister les fichiers du dossier Projets",
         main_issue="boucle de retries sur drive_list_files, 12 tentatives identiques"),
    dict(slug="dead_end_replan_thrash", status="failed", quality_score=20,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=False, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Préparer le rapport hebdomadaire dev",
         main_issue="4 replans successifs sans progression mesurable"),
    dict(slug="provider_thrash_midmission", status="completed", quality_score=50,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=False, critic_model="mistral-large-3",
         tier_llm="B", prompt_version="benchv1",
         goal="Compiler les statistiques GitHub du dépôt",
         main_issue="bascule de provider 3 fois, perd le contexte d'outil entre les tours"),
    dict(slug="redundant_tool_calls", status="completed", quality_score=55,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=False, critic_model="gemma-4-e4b-it",
         tier_llm="MAINTENANCE", prompt_version="benchv1",
         goal="Donner la météo de demain à Lyon",
         main_issue="appelle trois fois le même outil de lecture pour la même donnée"),
    dict(slug="scope_creep", status="completed", quality_score=48,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=False, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Renommer un fichier dans le Drive",
         main_issue="exécute des actions hors du goal initial (suppression de fichiers voisins)"),

    # ── Wrong tool / wrong args (actionable, honest) ──
    dict(slug="wrong_tool_calendar", status="failed", quality_score=15,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Ajouter un rappel dentiste mardi 14h",
         main_issue="a utilisé system_list_scheduled_tasks au lieu de calendar_create_event"),
    dict(slug="wrong_args_excel", status="completed", quality_score=45,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=False, critic_model="mistral-large-3",
         tier_llm="C", prompt_version="benchv1",
         goal="Additionner la colonne des montants",
         main_issue="mauvaise plage de colonnes passée à sheets_update_range"),
    dict(slug="format_ignored", status="completed", quality_score=44,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=False, critic_model="gemma-4-e4b-it",
         tier_llm="MAINTENANCE", prompt_version="benchv1",
         goal="Exporter la liste des contacts en CSV",
         main_issue="ignore le format de sortie demandé (tableau markdown au lieu de CSV)"),

    # ── Gave up / external / resource (actionable, honest) ──
    dict(slug="gave_up_early", status="aborted", quality_score=25,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Récupérer le code MFA reçu par mail",
         main_issue="abandonne après une seule erreur 429 sans tentative de retry"),
    dict(slug="budget_exhausted", status="failed", quality_score=30,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=False, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Analyser les 200 derniers mails et les classer",
         main_issue="budget tokens épuisé sur un sous-but secondaire avant l'objectif principal"),
    dict(slug="cascade_tool_error", status="aborted", quality_score=12,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=True, critic_model="mistral-large-3",
         tier_llm="C", prompt_version="benchv1",
         goal="Publier le post sur les réseaux",
         main_issue="erreur outil en chaîne, abandon propre mais aucun résultat livré"),
    dict(slug="hitl_stuck_timeout", status="aborted", quality_score=22,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="gemma-4-e4b-it",
         tier_llm="MAINTENANCE", prompt_version="benchv1",
         goal="Supprimer définitivement les mails de la corbeille",
         main_issue="bloqué en hitl_wait, l'utilisateur n'a jamais répondu à la confirmation"),

    # ── Memory / constraint misuse (actionable, honest) ──
    dict(slug="ignored_constraint", status="failed", quality_score=28,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Réserver un créneau de réunion",
         main_issue="ignore une contrainte mémoire CONSTRAINT explicite (pas de réunion le vendredi)"),
    dict(slug="stale_memory_used", status="completed", quality_score=52,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="mistral-large-3",
         tier_llm="C", prompt_version="benchv1",
         goal="Envoyer un message au contact habituel",
         main_issue="s'appuie sur une donnée mémoire périmée (ancien numéro de téléphone)"),

    # ── Capture boundary cases (actionable side) ──
    dict(slug="boundary_score_59", status="completed", quality_score=59,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=False, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Trier les photos du dossier vacances",
         main_issue="résultat juste en dessous du seuil de qualité acceptable"),

    # ── Non-actionable : good honest missions (→ skipped, no FailureCase) ──
    dict(slug="exemplary_completed", status="completed", quality_score=95,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=False, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Créer un événement agenda pour le rendez-vous",
         main_issue=None),
    dict(slug="good_minor_churn", status="completed", quality_score=78,
         honest_completion=True, wasted_effort=True,
         user_should_have_been_warned=False, critic_model="mistral-large-3",
         tier_llm="C", prompt_version="benchv1",
         goal="Télécharger la pièce jointe du dernier mail",
         main_issue="un retry mais résultat final propre et complet"),
    dict(slug="good_warned_user", status="completed", quality_score=72,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Envoyer un rappel à toute la liste de diffusion",
         main_issue="a honnêtement prévenu d'une limite de quota, résultat livré"),
    dict(slug="solid_failed_but_honest", status="failed", quality_score=68,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=True, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Réserver un rendez-vous médecin via Doctolib",
         main_issue="échec dû à une API tierce indisponible, géré et signalé proprement"),
    dict(slug="high_score_aborted_honest", status="aborted", quality_score=64,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=False, critic_model="gemma-4-e4b-it",
         tier_llm="MAINTENANCE", prompt_version="benchv1",
         goal="Préparer un brouillon de réponse",
         main_issue=None),
    dict(slug="boundary_score_60", status="completed", quality_score=60,
         honest_completion=True, wasted_effort=False,
         user_should_have_been_warned=False, critic_model="deepseek-v4-pro",
         tier_llm="C", prompt_version="benchv1",
         goal="Classer les reçus du mois",
         main_issue="résultat tout juste au seuil de qualité acceptable"),
]


def is_actionable(profile: dict[str, Any]) -> bool:
    """Mirror the ``capture_from_mission_critique`` filter exactly :
    a critique is captured (→ FailureCase) iff quality_score < 60 OR the
    completion was dishonest."""
    return profile["quality_score"] < 60 or not profile["honest_completion"]


def _title(slug: str) -> str:
    return slug.replace("_", " ").strip().capitalize()


def _scenario_filename(idx: int, slug: str) -> str:
    return f"{_FILE_PREFIX}{idx:02d}_{slug}.py"


def _render_scenario(idx: int, profile: dict[str, Any]) -> str:
    """Render one self-contained, AUTO-GENERATED scenario module."""
    actionable = is_actionable(profile)
    title = _title(profile["slug"])
    expect = "→ FailureCase" if actionable else "→ skipped (no capture)"
    desc = (
        f"{profile['status']} mission, score {profile['quality_score']}, "
        f"honest={profile['honest_completion']} {expect}. Asserts the "
        f"capture filter, stable pattern_hash, and learning-report round-trip."
    )
    return f'''# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/{_scenario_filename(idx, profile["slug"])}
# @brief      Sprint 3.7.3 J2 — critique-replay scenario CRIT-{idx:02d} ({profile["slug"]}).
#
#             *** AUTO-GENERATED by bench/gen_critique_scenarios.py — do NOT
#             edit by hand. Change the CATALOGUE there and re-run --write. ***
#
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Critique-replay scenario CRIT-{idx:02d} — {title}."""
from __future__ import annotations


NAME = "CRIT-{idx:02d} — {title}"
DESCRIPTION = {desc!r}
TAGS = ["shallow"]

# ── Frozen verdict profile ──────────────────────────────────────────────
_STATUS = {profile["status"]!r}
_GOAL = {profile["goal"]!r}
_CRITIC_MODEL = {profile["critic_model"]!r}
_TIER_LLM = {profile["tier_llm"]!r}
_PROMPT_VERSION = {profile["prompt_version"]!r}
_QUALITY_SCORE = {profile["quality_score"]!r}
_HONEST_COMPLETION = {profile["honest_completion"]!r}
_WASTED_EFFORT = {profile["wasted_effort"]!r}
_USER_SHOULD_HAVE_BEEN_WARNED = {profile["user_should_have_been_warned"]!r}
_MAIN_ISSUE = {profile["main_issue"]!r}
# quality_score < 60 OR dishonest → the critique is actionable.
_EXPECT_FAILURE_CASE = {actionable!r}


async def run() -> dict:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.database import async_session
    from app.models.failure_case import FailureCase
    from app.routers.learning_report import _load_mission_critiques
    from app.services.learning.failure_capture import (
        SIGNAL_MISSION_CRITIQUE,
        _fingerprint,
        capture_from_mission_critique,
    )
    from bench.scenarios._base import (
        from_checks,
        seed_mission_with_critique,
        throwaway_user,
    )

    async with throwaway_user("bench_crit") as uid:
        mission_id, critique_id = await seed_mission_with_critique(
            uid,
            status=_STATUS,
            goal=_GOAL,
            critic_model=_CRITIC_MODEL,
            quality_score=_QUALITY_SCORE,
            honest_completion=_HONEST_COMPLETION,
            wasted_effort=_WASTED_EFFORT,
            user_should_have_been_warned=_USER_SHOULD_HAVE_BEEN_WARNED,
            main_issue=_MAIN_ISSUE,
            tier_llm=_TIER_LLM,
            prompt_version=_PROMPT_VERSION,
        )

        checks: dict[str, bool] = {{
            "critique_persisted": bool(mission_id) and critique_id is not None,
        }}

        # 1. Replay the real failure_capture actionability filter.
        fc_id = await capture_from_mission_critique(
            signal_id=critique_id,
            user_id=uid,
            mission_id=mission_id,
            critic_model=_CRITIC_MODEL,
            quality_score=_QUALITY_SCORE,
            honest_completion=_HONEST_COMPLETION,
            wasted_effort=_WASTED_EFFORT,
            user_should_have_been_warned=_USER_SHOULD_HAVE_BEEN_WARNED,
            main_issue=_MAIN_ISSUE,
            tier_llm=_TIER_LLM,
            prompt_version=_PROMPT_VERSION,
        )

        if _EXPECT_FAILURE_CASE:
            checks["actionable_failure_case_created"] = fc_id is not None
            async with async_session() as db:
                fc = (await db.execute(
                    select(FailureCase).where(FailureCase.id == fc_id)
                )).scalar_one_or_none() if fc_id is not None else None
            checks["failure_case_shape"] = bool(
                fc is not None
                and fc.signal_table == SIGNAL_MISSION_CRITIQUE
                and fc.mission_id == mission_id
                and fc.user_id == uid
            )
            # The clustering key must stay deterministic AND match the
            # documented contract — a V2 tool changing it silently would
            # split/merge skill candidates wrongly.
            issue_kw = (_MAIN_ISSUE or "")[:80].strip().lower()
            expected_fp = _fingerprint(
                SIGNAL_MISSION_CRITIQUE, str(_QUALITY_SCORE < 30), issue_kw,
            )
            checks["pattern_hash_stable"] = bool(
                fc is not None and fc.pattern_hash == expected_fp
            )
        else:
            # A high-quality honest mission must NOT spawn a FailureCase.
            checks["non_actionable_skipped"] = fc_id is None
            async with async_session() as db:
                leaked = (await db.execute(
                    select(FailureCase).where(FailureCase.mission_id == mission_id)
                )).scalar_one_or_none()
            checks["no_failure_case_leak"] = leaked is None

        # 2. Report round-trip — the critique must surface in the join.
        since = datetime.now(timezone.utc) - timedelta(days=1)
        critiques = await _load_mission_critiques(uid, since)
        match = next(
            (c for c in critiques if c["mission_id"] == mission_id), None
        )
        checks["report_roundtrip"] = bool(
            match is not None
            and match["quality_score"] == _QUALITY_SCORE
            and match["status"] == _STATUS
        )

        return from_checks(
            checks,
            mission_id=mission_id,
            critique_id=critique_id,
            failure_case_id=fc_id,
            expected_failure_case=_EXPECT_FAILURE_CASE,
        )
'''


def _validate_catalogue() -> list[str]:
    """Return a list of problems (empty = OK). Keeps the catalogue honest."""
    problems: list[str] = []
    slugs = [p["slug"] for p in CATALOGUE]
    if len(slugs) != len(set(slugs)):
        dupes = sorted({s for s in slugs if slugs.count(s) > 1})
        problems.append(f"duplicate slugs: {dupes}")
    valid_status = {"completed", "failed", "aborted"}
    for p in CATALOGUE:
        if p["status"] not in valid_status:
            problems.append(f"{p['slug']}: bad status {p['status']!r}")
        if not (0 <= p["quality_score"] <= 100):
            problems.append(f"{p['slug']}: score out of range {p['quality_score']}")
    return problems


def _plan_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, p in enumerate(CATALOGUE, start=1):
        rows.append({
            "idx": idx,
            "file": _scenario_filename(idx, p["slug"]),
            "slug": p["slug"],
            "status": p["status"],
            "score": p["quality_score"],
            "honest": p["honest_completion"],
            "actionable": is_actionable(p),
        })
    return rows


def _print_plan() -> None:
    rows = _plan_rows()
    n_act = sum(1 for r in rows if r["actionable"])
    print(f"Critique-replay catalogue — {len(rows)} scenarios "
          f"({n_act} actionable → FailureCase, {len(rows) - n_act} skipped)\n")
    print(f"  {'##':>2}  {'status':<9} {'score':>5} {'honest':<6} "
          f"{'→cap':<5} file")
    print("  " + "-" * 68)
    for r in rows:
        print(f"  {r['idx']:>2}  {r['status']:<9} {r['score']:>5} "
              f"{str(r['honest']):<6} {('yes' if r['actionable'] else 'no'):<5} "
              f"{r['file']}")
    # Distribution digest
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    print("\n  by status :", ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    buckets = {"0-29": 0, "30-59": 0, "60-79": 0, "80-100": 0}
    for r in rows:
        s = r["score"]
        key = "0-29" if s < 30 else "30-59" if s < 60 else "60-79" if s < 80 else "80-100"
        buckets[key] += 1
    print("  by score  :", ", ".join(f"{k}={v}" for k, v in buckets.items()))


def _existing_generated() -> list[Path]:
    return sorted(_CANONICAL_DIR.glob(f"{_FILE_PREFIX}*.py"))


def _clean() -> int:
    removed = _existing_generated()
    for f in removed:
        f.unlink()
    print(f"Removed {len(removed)} generated scenario file(s).")
    return 0


def _write() -> int:
    # Idempotent: wipe stale generated files first so a renamed/removed
    # catalogue entry never leaves an orphan scenario behind.
    for f in _existing_generated():
        f.unlink()
    _CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for idx, p in enumerate(CATALOGUE, start=1):
        path = _CANONICAL_DIR / _scenario_filename(idx, p["slug"])
        path.write_text(_render_scenario(idx, p), encoding="utf-8")
        written += 1
    print(f"Wrote {written} scenario file(s) → "
          f"{_CANONICAL_DIR.relative_to(_HERE.parent)}/")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.gen_critique_scenarios",
        description="Generate the critique-replay canonical scenario batch.",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true",
                   help="Emit the scenario_critique_*.py files.")
    g.add_argument("--clean", action="store_true",
                   help="Remove every generated scenario_critique_*.py file.")
    args = parser.parse_args(argv or [])

    problems = _validate_catalogue()
    if problems:
        print("Catalogue validation FAILED:", file=sys.stderr)
        for prob in problems:
            print(f"  - {prob}", file=sys.stderr)
        return 1

    if args.clean:
        return _clean()
    if args.write:
        return _write()

    # Default: dry-run.
    _print_plan()
    print("\n(dry-run — nothing written. Re-run with --write to emit files.)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
