# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_y_free_mission_end_to_end.py
# @brief      Une mission LIBRE de bout en bout : plan genere par le LLM,
#             droit a l'erreur, abandon d'etape, replan apres echecs
#             repetes, et un resume qui ne ment pas.
# @license    Elastic License 2.0
# =============================================================================
"""Scénario Y — la mission LIBRE de bout en bout (29/08/2026).

POURQUOI, EN PLUS DU SCÉNARIO X
-------------------------------
X couvre la mission STRUCTURÉE (spec YAML). Mais un utilisateur qui installe
Ely n'écrit pas de YAML : il tape un but en français et lance. C'est le
chemin LIBRE, et il a sa propre mécanique, qu'aucun scénario n'exerçait :

- le plan est GÉNÉRÉ par le planificateur (X le court-circuite) ;
- `consecutive_failures` compte, et à trois il replanifie — une bascule que
  la spec n'a jamais ;
- `replan_node` reconstruit un plan et le graphe repart dessus.

C'est aussi le chemin de l'incident du 26/08 : une étape refusée était
rejouée indéfiniment jusqu'à épuiser le budget (103 041 / 100 000 tokens),
parce que `_next_pending_step` ne saute que `done` et `skipped`, jamais
`failed`.

CE QU'IL COUVRE
---------------
- le planificateur reçoit la date du jour ET le catalogue d'outils ;
- le plan généré pilote l'exécution (les `tool_hint` sont suivis) ;
- une étape refusée garde son droit à l'erreur, puis est ABANDONNÉE —
  elle ne bloque pas la mission et ne consomme pas le budget ;
- le compteur d'échecs monte sur une mission libre (contrairement à une
  spec) et déclenche un replan ;
- `replan_node` produit un plan exploitable même quand le modèle ne rend
  pas du JSON — il ne tue pas la mission ;
- le résumé final nomme les étapes abandonnées.
"""
from __future__ import annotations

import json
import types
from datetime import datetime
from zoneinfo import ZoneInfo

NAME = "Y — mission libre de bout en bout"
DESCRIPTION = (
    "Un simple but en français : plan généré par le planificateur, étape "
    "refusée puis abandonnée après ses tentatives, replan déclenché par les "
    "échecs répétés, et un résumé final qui avoue ce qui a été sauté."
)
TAGS = ["medium"]

_BUT = "Trouve la météo et envoie-la moi."

# Le plan que le planificateur « génère » : la première étape passe, les
# deux suivantes sont refusées.
#
# Il en faut DEUX en échec : depuis le droit à l'erreur (26/08), une étape
# est abandonnée au bout de 2 tentatives, donc `consecutive_failures` ne
# peut plus atteindre 3 sur une seule. Le replan ne se déclenche que sur
# des échecs RÉPARTIS — contrepartie assumée de cette borne, que ce
# scénario pinne pour qu'elle ne dérive pas en silence.
_PLAN_V1 = {
    "steps": [
        {"id": "1", "description": "Relève la météo du jour",
         "tool_hint": "weather_get"},
        {"id": "2", "description": "Envoie le bulletin",
         "tool_hint": "telegram_send_message"},
        {"id": "3", "description": "Préviens sur le second canal",
         "tool_hint": "telegram_send_message"},
    ],
}


class _FakeLLM:
    """Planificateur, acteur et évaluateur, distingués par leur prompt."""

    def __init__(self, journal: dict):
        self._j = journal

    async def ainvoke(self, messages, **_kw):
        texte = _prompt_text(messages)

        # 1. Planificateur : on note ce qu'il a REÇU, puis on rend un plan.
        if "Goal de l'utilisateur" in texte:
            self._j["prompt_planificateur"] = texte
            return types.SimpleNamespace(content=json.dumps(_PLAN_V1))

        # 2. Replanificateur : il répond en PROSE, pas en JSON. C'est le cas
        #    qui levait `UnboundLocalError` et tuait la mission.
        if "replanificateur" in texte.lower() or "NOUVEAU plan" in texte:
            self._j["replan_demande"] = True
            return types.SimpleNamespace(
                content="Bien sûr ! Je propose de reprendre autrement…"
            )

        # 3. Évaluateur : l'étape 2 est toujours refusée.
        if "success" in texte and "all_done" in texte:
            refus = self._j.get("dernier_outil") == "telegram_send_message"
            return types.SimpleNamespace(content=json.dumps({
                "success": not refus,
                "reason": "envoi refusé par le canal" if refus else "relevé",
                "all_done": False,
            }))

        # 4. Acteur.
        return types.SimpleNamespace(
            content="", tool_calls=_tool_call_for(texte, self._j),
        )

    def bind_tools(self, tools, **_kw):
        self._j.setdefault("outils_lies", []).append(
            [getattr(t, "name", "?") for t in tools]
        )
        return self


def _prompt_text(messages) -> str:
    morceaux = []
    for m in messages or ():
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        morceaux.append(c if isinstance(c, str) else str(c))
    return "\n".join(morceaux)


def _etape_courante(prompt: str) -> str:
    marqueur = "Étape courante à exécuter : «"
    i = prompt.find(marqueur)
    return prompt[i + len(marqueur):].split("»")[0] if i >= 0 else prompt


def _tool_call_for(prompt: str, journal: dict) -> list[dict]:
    etape = _etape_courante(prompt)

    def _call(nom, args):
        journal["dernier_outil"] = nom
        journal.setdefault("outils_appeles", []).append(nom)
        return [{"name": nom, "args": args, "id": f"call_{nom}"}]

    if "météo" in etape or "Relève" in etape:
        return _call("weather_get", {"city": "Paris"})
    return _call("telegram_send_message", {"text": "bulletin"})


async def run() -> dict:
    from langgraph.checkpoint.memory import MemorySaver

    from app.agent.missions.graph import build_mission_graph
    from app.services import mission_service
    from app.skills.builtin import register_all
    from bench.scenarios._base import from_checks, throwaway_user

    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp

    register_all()
    journal: dict = {}
    faux = _FakeLLM(journal)

    orig = {
        "planner": mn._get_planner_llm,
        "eval": mn._get_evaluator_llm,
        "tier": lp.get_llm_for_tier,
        "fallbacks": lp.get_fallback_llms,
        "dispatch": mn.dispatch_tool,
    }

    async def _dispatch(tool_name, _args, _cid, _uid, **_kw):
        if tool_name == "weather_get":
            return "Paris : 21 °C, ciel dégagé.", True
        return "Erreur : canal indisponible", False

    mn._get_planner_llm = lambda *a, **k: faux
    mn._get_evaluator_llm = lambda **_kw: faux
    lp.get_llm_for_tier = lambda _t: faux
    lp.get_fallback_llms = lambda: []
    mn.dispatch_tool = _dispatch
    try:
        async with throwaway_user("bench_y") as uid:
            m = await mission_service.create_mission(
                user_id=uid, title="Bench Y", goal=_BUT,
            )
            graph = build_mission_graph().compile(checkpointer=MemorySaver())
            config = {"configurable": {"thread_id": m.id}}
            etat: dict = {}
            for _ in range(14):
                etat = await graph.ainvoke(
                    {"mission_id": m.id, "user_id": uid, "goal": _BUT},
                    config=config,
                )
                if etat.get("done") or etat.get("failed"):
                    break
    finally:
        mn._get_planner_llm = orig["planner"]
        mn._get_evaluator_llm = orig["eval"]
        lp.get_llm_for_tier = orig["tier"]
        lp.get_fallback_llms = orig["fallbacks"]
        mn.dispatch_tool = orig["dispatch"]

    prompt_plan = journal.get("prompt_planificateur", "")
    maintenant = datetime.now(ZoneInfo("Europe/Paris"))
    etapes = {s.get("id"): s for s in (etat.get("plan_json") or {}).get("steps", [])}
    etape_2 = etapes.get("2", {})
    resume = etat.get("final_summary") or ""
    appels = journal.get("outils_appeles") or []

    checks = {
        # Le planificateur travaille avec la date du jour et le catalogue.
        "planificateur_a_la_date": str(maintenant.year) in prompt_plan,
        "planificateur_a_le_catalogue": "weather_get" in prompt_plan,
        # Le plan généré pilote vraiment l'exécution.
        "plan_genere_pilote_l_execution": "weather_get" in appels,
        # Droit à l'erreur PUIS abandon — le défaut du 26/08 : sans la
        # borne, l'étape refusée était rejouée jusqu'à épuiser le budget.
        "etape_refusee_compte_ses_tentatives": etape_2.get("attempts", 0) >= 2,
        "etape_refusee_abandonnee": etape_2.get("status") == "skipped",
        "raison_de_l_abandon_conservee": bool(etape_2.get("abandon_reason")),
        # Une mission LIBRE compte ses échecs (contrairement à une spec) et
        # peut replanifier — `replan_node` ne doit pas tuer la mission même
        # quand le modèle répond en prose.
        "replan_declenche": bool(journal.get("replan_demande")),
        "mission_survit_au_replan": not etat.get("failed"),
        # Et le résumé ne ment pas.
        "mission_terminee": bool(etat.get("done")),
        "resume_avoue_l_abandon": "abandonn" in resume.lower(),
    }
    return from_checks(
        checks,
        outils_appeles=appels,
        etape_2=etape_2.get("status"),
        tentatives=etape_2.get("attempts"),
        resume=resume[:200],
    )
