#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/run_catalog_ab.py
# @brief      Banc A/B — le modèle choisit-il aussi bien son outil parmi 206
#             que parmi les 87 du profil ?
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Mesure la justesse du choix d'outil selon la TAILLE du catalogue bindé.

**La question.** Le profil `default` ne couvre que 87 outils sur 206, et
16 familles entières en sont absentes (Sheets, Docs, PDF, Maps…). Élargir le
catalogue supprimerait ces trous, mais le commentaire d'origine du profil
posait l'hypothèse inverse : « le modèle apprend son catalogue par cœur ».
Hypothèse jamais mesurée.

**L'isolation.** Un appel LLM par cas, même prompt, même modèle, **seule la
liste d'outils change**. Pas de passage par le graphe : la boucle de
vérification et les relances ajouteraient du bruit étranger à la question.

**Les deux moitiés.**

- ``REGRESSION`` — le bon outil EST déjà au profil. Répond à « 206 fait-il
  PIRE ? ». C'est le risque.
- ``TROU`` — le bon outil est ABSENT du profil. Répond à « 206 répare-t-il ? ».
  C'est le gain attendu.

**La règle de décision, posée AVANT de lancer** (sans quoi un résultat mitigé
se lit toujours comme un succès) :

    on bascule si REGRESSION ne perd pas plus d'UN cas sur la référence
    ET si TROU progresse nettement.

⚠️ **Le modèle est visé explicitement.** La chaîne `complex` commence par
`kimi-k3`, qui échoue en `bad_request` à chaque tour depuis le 28/07 et bascule
sur `gpt-5.6-terra`. Passer par `get_llm_for_tier` mesurerait donc un modèle
qui ne sert jamais.

⚠️ **Limites assumées.** La vérité terrain est écrite à la main : seules les
demandes à réponse unique sont retenues. Un seul appel est **pessimiste** pour
les deux bras (en vrai, `find_tool` rattrape au tour suivant) — mais également,
donc la comparaison tient. Le modèle n'étant pas déterministe, chaque cas est
rejoué ``--runs`` fois.

Usage ::

    docker exec -i physicalagent-master-backend-1 /app/.venv/bin/python \\
        -m bench.run_catalog_ab --runs 3

    # coup d'essai sur 4 cas
    … -m bench.run_catalog_ab --runs 1 --limit 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

# Les modèles benchés, par nom court. Le banc DOIT viser explicitement :
# passer par `get_llm_for_tier` mesurerait la tête de chaîne du moment, qui
# change quand la configuration change.
PROVIDERS = {
    "terra": "5fdc8850-06be-4e39-b46c-1824a102a461",   # openai_codex / gpt-5.6-terra
    "kimi":  "7e818ccc-d603-45b1-bce3-10b0b17f9773",   # moonshot / kimi-k3
    "sol":   "a175d876-1adb-4919-93ee-590c628ac8e3",   # openai_codex / gpt-5.6-sol
}

SYSTEM = (
    "Tu es Ely, l'assistant personnel de Franck. Choisis et appelle l'outil "
    "approprié à la demande. N'explique pas, ne commente pas : appelle l'outil."
)


@dataclass(frozen=True)
class Case:
    prompt: str
    expected: str
    half: str          # "regression" | "trou"


# ── Moitié RÉGRESSION — le bon outil est DÉJÀ au profil ──────────────────────
REGRESSION: tuple[Case, ...] = tuple(
    Case(p, e, "regression") for p, e in (
        ("Prépare un brouillon de mail à gert@exemple.fr, objet « Point mardi », "
         "corps « Es-tu dispo mardi ? ».", "gmail_create_draft"),
        ("Liste mes derniers mails reçus.", "gmail_list_emails"),
        ("Enregistre dans mon Drive les pièces jointes du mail dont l'identifiant "
         "est 18f2a9c4b1.", "gmail_save_attachments_to_drive"),
        ("Crée un dossier « Factures 2026 » dans mon Drive.", "drive_create_folder"),
        ("Montre-moi les fichiers de mon Drive.", "drive_list_files"),
        ("Trouve les fichiers en double dans mon Drive.", "drive_find_duplicates"),
        ("Quels onglets sont ouverts dans mon navigateur ?", "browser_list_tabs"),
        ("Cherche « facture » dans mon historique de navigation.",
         "browser_history_search"),
        ("Dans mes marque-pages, trouve ceux qui parlent de Docker.",
         "browser_bookmarks_search"),
        ("Retiens que je préfère les réunions le matin.", "memory_archive"),
        ("Qu'as-tu enregistré sur mes préférences ?", "memory_view_profile"),
        ("Crée une note intitulée « Idées CatalogMaker ».", "notes_create"),
        ("Montre-moi mes notes.", "notes_list"),
        ("Programme une tâche chaque lundi à 9 h qui me fait un point.",
         "scheduler_create_task"),
        ("Quelles tâches planifiées ai-je en ce moment ?", "scheduler_list_tasks"),
        ("Cherche sur le web les nouveautés de LangGraph.", "web_search"),
        ("Donne-moi les actualités du jour sur l'intelligence artificielle.",
         "web_search_news"),
        ("Liste le contenu du dossier /Users/franck/Downloads.", "desktop_list_dir"),
        ("Calcule l'empreinte SHA-256 du fichier /tmp/rapport.pdf.",
         "desktop_hash_file"),
        ("Donne-moi les statistiques du dépôt GitHub franckolv-dev/ElyAgent.",
         "github_repo_stats"),
    )
)

# ── Moitié TROU — le bon outil est ABSENT du profil ──────────────────────────
TROU: tuple[Case, ...] = tuple(
    Case(p, e, "trou") for p, e in (
        ("Convertis le fichier /tmp/rapport.pdf en document Word.", "pdf_to_docx"),
        ("Lis-moi le texte du PDF /tmp/rapport.pdf.", "pdf_read"),
        ("Combien de pages fait le PDF /tmp/rapport.pdf ?", "pdf_info"),
        ("Crée un tableur Google pour suivre mes dépenses.",
         "sheets_create_spreadsheet"),
        ("Ajoute la ligne « Café ; 3,50 » à la fin de la feuille « Dépenses » du "
         "tableur Google 1AbCdEf.", "sheets_append_rows"),
        ("Crée un document Google Docs intitulé « Compte-rendu ».",
         "docs_create_document"),
        ("Lis le contenu du document Google Docs 1XyZ789.", "docs_read_document"),
        ("Supprime l'événement d'agenda dont l'identifiant est evt_4471.",
         "calendar_delete_event"),
        ("Suis-je libre mardi après-midi ?", "calendar_check_availability"),
        ("Organise une visioconférence avec Gert jeudi à 14 h.",
         "calendar_create_meet_event"),
        ("Ajoute Gert Dupont à mes contacts.", "contacts_create"),
        ("Montre-moi mes contacts.", "contacts_list"),
        ("Donne-moi l'itinéraire de Lille à Paris.", "maps_directions"),
        ("Récupère la transcription de la vidéo YouTube "
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ.", "youtube_transcript"),
        ("Génère un QR code pour l'adresse https://agent-ely.fr.", "qrcode_generate"),
    )
)

CASES: tuple[Case, ...] = REGRESSION + TROU


@dataclass
class Outcome:
    case: Case
    arm: str
    called: list[str] = field(default_factory=list)
    ok: bool = False
    error: str = ""
    seconds: float = 0.0


# Un fournisseur saturé n'est PAS un mauvais choix d'outil. Sans cette
# distinction, un 429 de Moonshot compterait comme une erreur de sélection et
# le banc mesurerait la capacité du fournisseur au lieu du modèle.
_TRANSIENT = ("ratelimit", "overload", "timeout", "503", "502", "429")


def _is_transient(exc: Exception) -> bool:
    blob = f"{type(exc).__name__} {exc}".lower()
    return any(marker in blob for marker in _TRANSIENT)


async def _run_one(bound, case: Case, arm: str, attempts: int = 4) -> Outcome:
    from langchain_core.messages import HumanMessage, SystemMessage

    started = time.time()
    last = ""
    for attempt in range(attempts):
        try:
            reply = await bound.ainvoke(
                [SystemMessage(content=SYSTEM), HumanMessage(content=case.prompt)]
            )
            called = [c["name"] for c in (reply.tool_calls or [])]
            return Outcome(case, arm, called, case.expected in called, "",
                           time.time() - started)
        except Exception as exc:  # noqa: BLE001 — un échec est une donnée
            last = f"{type(exc).__name__}: {exc}"[:160]
            if not _is_transient(exc):
                return Outcome(case, arm, [], False, last, time.time() - started)
            await asyncio.sleep(5 * (attempt + 1))
    # Épuisé sur du transitoire : INDISPONIBLE, pas « mauvais choix ».
    return Outcome(case, arm, [], False, f"INDISPONIBLE {last}",
                   time.time() - started)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3, help="passes par cas (défaut 3)")
    ap.add_argument("--limit", type=int, default=0, help="ne garder que N cas")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="terra",
                    help="modèle à mesurer (défaut terra)")
    args = ap.parse_args()

    from app.services.llm_provider import (
        ComplexityTier, build_llm_for_provider, load_llm_settings_from_db,
    )
    from app.agent.helpers.bind_tools import _bind_tools_smart
    from app.skills.builtin import register_all
    from app.skills import get_skill_registry
    from app.agent.toolset_profiles import resolve_profile_tools

    await load_llm_settings_from_db()
    register_all()

    every = get_skill_registry().all_tools
    profile = resolve_profile_tools("default", every)
    llm = build_llm_for_provider(PROVIDERS[args.provider], ComplexityTier.COMPLEX)
    if llm is None:
        print("!! modèle cible indisponible — banc annulé")
        return 1

    model = getattr(llm, "model_name", getattr(llm, "model", "?"))
    arms = {"profil-87": profile, "complet-206": every}
    cases = CASES[: args.limit] if args.limit else CASES

    print(f"modèle   : {model}")
    print(f"bras     : " + ", ".join(f"{k} ({len(v)} outils)" for k, v in arms.items()))
    print(f"cas      : {len(cases)}  ×  {args.runs} passe(s)  ×  {len(arms)} bras\n")

    bound = {name: _bind_tools_smart(llm, tools) for name, tools in arms.items()}
    results: list[Outcome] = []

    for index, case in enumerate(cases, 1):
        line = f"  [{index:>2}/{len(cases)}] {case.half:<10} {case.expected:<28}"
        marks = []
        for arm in arms:
            hits = 0
            for _ in range(args.runs):
                out = await _run_one(bound[arm], case, arm)
                results.append(out)
                hits += int(out.ok)
            marks.append(f"{arm}={hits}/{args.runs}")
        print(line + "  ".join(marks))

    # ── Synthèse ────────────────────────────────────────────────────────────
    print("\n" + "=" * 68)
    summary: dict[str, dict[str, dict[str, int]]] = {}
    for half in ("regression", "trou"):
        summary[half] = {}
        for arm in arms:
            sel = [r for r in results if r.case.half == half and r.arm == arm
                   and not r.error.startswith("INDISPONIBLE")]
            summary[half][arm] = {"ok": sum(r.ok for r in sel), "total": len(sel)}

    for half in ("regression", "trou"):
        print(f"\n{half.upper()}")
        for arm in arms:
            s = summary[half][arm]
            pct = 100.0 * s["ok"] / s["total"] if s["total"] else 0.0
            print(f"  {arm:<14} {s['ok']:>3}/{s['total']:<4} {pct:>5.1f} %")

    reg = summary["regression"]
    lost = reg["profil-87"]["ok"] - reg["complet-206"]["ok"]
    gain = summary["trou"]["complet-206"]["ok"] - summary["trou"]["profil-87"]["ok"]
    print(f"\nRÉGRESSION : {lost:+d} cas   ·   TROU : {gain:+d} cas")
    verdict = "BASCULER" if lost <= args.runs and gain > 0 else "NE PAS BASCULER"
    print(f"VERDICT (règle posée d'avance) : {verdict}")

    unavailable = [r for r in results if r.error.startswith("INDISPONIBLE")]
    errs = [r for r in results if r.error and r not in unavailable]
    if unavailable:
        print(f"\n⚠️  {len(unavailable)} appel(s) INDISPONIBLES (fournisseur saturé) "
              f"— exclus du score, pas comptés en échec")
    if errs:
        print(f"⚠️  {len(errs)} appel(s) en erreur — exemple : {errs[0].error}")

    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    payload = {
        "model": model,
        "runs": args.runs,
        "arms": {k: len(v) for k, v in arms.items()},
        "summary": summary,
        "verdict": verdict,
        "details": [
            {"prompt": r.case.prompt, "expected": r.case.expected,
             "half": r.case.half, "arm": r.arm, "called": r.called,
             "ok": r.ok, "error": r.error, "seconds": round(r.seconds, 2)}
            for r in results
        ],
    }
    dest = out_dir / f"catalog_ab_{args.provider}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ndétail écrit dans {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
