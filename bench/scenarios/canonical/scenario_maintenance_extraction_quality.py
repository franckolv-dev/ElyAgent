# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_maintenance_extraction_quality.py
# @brief      Examen d'extraction du tiers MAINTENANCE — gate OBLIGATOIRE avant
#             tout changement de modèle sur ce tiers (verdict LFM2.5, 12 juin).
# @license    Elastic License 2.0
# =============================================================================
"""Examen d'extraction mémoire — le scénario qui aurait évité l'épisode LFM2.5.

Le tiers MAINTENANCE écrit dans la mémoire long-terme : chaque erreur de
jugement y est invisible et composée. Le 12 juin 2026, LFM2.5 8B A1B (mis sur
ce tiers « au ressenti ») a été mesuré : URLs ratées, fait FABRIQUÉ par
contamination des exemples du prompt (« projet IA nommé ELY »), JSON vide en
budget de tokens serré (préambule de raisonnement). Gemma 4 E4B : 4/4, zéro
invention. Ce scénario rejoue cet examen contre LE MODÈLE CONFIGURÉ sur le
tiers via le VRAI chemin de prod (`MaintenanceAgentRapid._extract_facts`).

Tag « deep » : appelle le LLM réel (LM Studio local) — exclu du nightly CI,
à lancer À LA MAIN avant d'adopter un nouveau modèle de maintenance :

    DATABASE_URL="sqlite+aiosqlite:///./bench_gate.db" \\
    PYTHONPATH=. backend/.venv/bin/python -m bench.run_canonical --tag deep
"""
from __future__ import annotations

NAME = "maintenance — examen d'extraction (gate changement de modèle)"
DESCRIPTION = (
    "Le modèle configuré sur le tiers MAINTENANCE extrait les faits d'une "
    "conversation à vérité connue : il doit rappeler les 4 faits durables "
    "plantés (dont 2 URLs de profils — le cas terrain du 12 juin), ignorer "
    "le bruit éphémère, et SURTOUT ne rien fabriquer (piège : l'exemple "
    "« projet IA nommé ELY » du prompt ne doit pas ressortir comme fait)."
)
TAGS = ["deep"]

# Conversation à vérité connue. Faits durables plantés : 2 URLs de profils,
# 1 préférence anti-markdown, 1 contexte (club badminton). Bruit à ignorer :
# météo du jour, question fibonacci. Le transcript ne mentionne JAMAIS de
# « projet IA » — toute mention dans les faits = contamination des exemples.
_CONVERSATION = """\
User: salut, avant que j'oublie : retiens mes profils sociaux pour de bon — \
https://www.linkedin.com/in/jdupont-test et https://bsky.app/profile/jdupont.bsky.social
Assistant: C'est noté, j'ai enregistré tes deux profils.
User: quelle est la météo aujourd'hui à Poitiers ?
Assistant: Aujourd'hui à Poitiers : 21°C, éclaircies l'après-midi.
User: super. au fait, arrête définitivement les tableaux markdown dans tes réponses, je déteste ça
Assistant: Compris, plus aucun tableau markdown à l'avenir.
User: c'est quoi le 12e terme de la suite de fibonacci ?
Assistant: F(12) = 144.
User: ok. demain j'emmène ma fille Léa (elle a 8 ans) à son tournoi — je gère \
le club de badminton de Neuville, on s'entraîne tous les mardis
Assistant: Bonne chance à Léa pour son tournoi !
User: merci, à plus"""


async def run() -> dict:
    from app.services.memory.maintenance_rapid import get_maintenance_agent_rapid
    from bench.scenarios._base import from_checks

    # Examiner le modèle RÉELLEMENT configuré sur le tiers (overrides DB),
    # pas le défaut env — c'est tout l'objet du gate. Best-effort : sans DB
    # accessible, get_llm_for_tier retombe sur la config env.
    try:
        from app.services.llm_provider import load_llm_settings_from_db
        await load_llm_settings_from_db()
    except Exception:
        pass

    agent = get_maintenance_agent_rapid()
    facts = await agent._extract_facts(_CONVERSATION)

    blob = " ".join(str(f.get("fact", "")) for f in facts).lower()
    types_ok = all(
        f.get("type") in {"preference", "context", "event", "skill", "personal"}
        for f in facts
    )

    return from_checks(
        {
            # Un modèle qui pense trop / répond hors format → liste vide ici
            "json_parsed_some_facts": len(facts) > 0,
            "respects_max_5": len(facts) <= 5,
            "facts_under_cap": all(
                len(str(f.get("fact", ""))) <= 250 for f in facts
            ),
            "valid_types": types_ok,
            # Rappel des faits plantés — les URLs sont LE cas terrain
            "recalls_linkedin_url": "linkedin.com/in/jdupont-test" in blob,
            "recalls_bluesky_url": "bsky.app/profile/jdupont" in blob,
            "recalls_markdown_preference": "markdown" in blob or "tableau" in blob,
            "recalls_badminton_context": "badminton" in blob,
            # Bruit éphémère : règles « ✗ À ÉVITER » du prompt
            "ignores_weather_noise": "météo" not in blob and "21°" not in blob,
            "ignores_fibonacci_noise": "fibonacci" not in blob and "144" not in blob,
            # LE piège anti-LFM : l'exemple du prompt ne doit JAMAIS devenir
            # un fait (fabrication par contamination — mesurée le 12 juin)
            "no_prompt_example_bleed": "projet ia" not in blob and "ely" not in blob,
        },
        extracted_facts=[
            {"type": f.get("type"), "fact": str(f.get("fact", ""))[:120]}
            for f in facts
        ],
    )
