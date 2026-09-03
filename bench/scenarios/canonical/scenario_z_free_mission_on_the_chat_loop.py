# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_z_free_mission_on_the_chat_loop.py
# @brief      Une mission LIBRE de bout en bout sur la boucle du CHAT : deux
#             reveils, le carnet pour memoire, les budgets pour bornes.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Scénario Z — la mission libre sur la boucle du chat (02/09/2026).

POURQUOI, EN PLUS DE X ET DE Y
------------------------------
X couvre la mission STRUCTURÉE (spec YAML) et Y la mission libre sur la
machine à états plan/act/eval/replan. Ce scénario couvre le chemin qui les
remplace pour la mission libre : le tour de chat automatisé.

La différence n'est pas cosmétique. Sur l'ancien chemin, le graphe SORT après
chaque tour et l'acteur repart d'un prompt reconstruit depuis SQL — c'est ce
qui lui faisait rouvrir quatre fois le même onglet LinkedIn le 31/08/2026,
parce qu'à chaque tour il avait oublié l'erreur du tour précédent. Ici il
tient UN fil : outil, résultat, outil suivant, jusqu'à sa réponse en texte.

CE QU'IL COUVRE
---------------
- un passage enchaîne plusieurs outils dans le MÊME fil et relit leurs
  résultats sans qu'on ait à les lui redire ;
- chaque outil passe par la passerelle des missions, avec l'identité de la
  mission — c'est elle qui porte la garde du mandat ;
- le carnet est la mémoire : le second réveil RELIT ce que le premier a fait
  et ne le refait pas ;
- le budget d'itérations mord AU MILIEU d'un passage : l'outil est refusé et
  le modèle est sommé de conclure, sans exception qui jetterait le travail ;
- la mission se termine sur la conclusion du modèle, avec un résumé.
"""
from __future__ import annotations

import os
import tempfile
import uuid

NAME = "Z — mission libre sur la boucle du chat"
DESCRIPTION = (
    "Deux réveils d'une mission libre exécutée comme un chat sans humain : "
    "outils enchaînés dans un seul fil, carnet relu au réveil suivant, "
    "budget qui mord au milieu du passage."
)
TAGS = ["medium"]

_BUT = "Releve les trois imprimeries de Lyon et note-les dans le tableur."


def _appel(nom: str, **args):
    from langchain_core.messages import AIMessage

    return AIMessage(content="", tool_calls=[
        {"name": nom, "args": args, "id": f"call_{nom}_{uuid.uuid4().hex[:4]}"},
    ])


def _texte(t: str):
    from langchain_core.messages import AIMessage

    return AIMessage(content=t)


class _ModeleScripte:
    """Rend ses réponses dans l'ordre, garde chaque prompt et chaque binding.

    Le juge de conformité tourne sur le même modèle : on le reconnaît à son
    prompt et on le laisse passer, sinon il consommerait le script.
    """

    def __init__(self, tours):
        self._tours = list(tours)
        self.prompts: list[str] = []
        self.outils_lies: list[str] = []

    def bind_tools(self, tools, **_kw):
        self.outils_lies = [getattr(t, "name", "?") for t in tools]
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        morceaux = []
        for m in messages or ():
            c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            morceaux.append(c if isinstance(c, str) else str(c))
        texte = "\n".join(morceaux)
        self.prompts.append(texte)
        if "Tu vérifies qu'un travail répond à la demande" in texte:
            return _texte("CONFORME")
        if not self._tours:
            return _texte("Plus rien à faire.")
        return self._tours.pop(0)


async def run() -> dict:
    from app.services import mission_service
    from bench.scenarios._base import from_checks, throwaway_user

    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp

    from app.agent.missions.chat_loop import (
        MARQUEUR_A_SUIVRE,
        run_mission_chat_passage,
    )

    journal: list[dict] = []

    async def _dispatch(nom, args, _cid, _uid, **kw):
        journal.append({"tool": nom, "args": args, "mission_id": kw.get("mission_id")})
        if nom == "web_search":
            return "PUBLIGIFTS, IMPRIM2 et TROISIEME sont les trois imprimeries.", True
        return f"{nom} : fait.", True

    orig = {
        "tier": lp.get_llm_for_tier,
        "fallbacks": lp.get_fallback_llms,
        "dispatch": mn.dispatch_tool,
        "ws": os.environ.get("MISSIONS_WORKSPACE_DIR"),
    }
    dossier = tempfile.TemporaryDirectory(prefix="bench_z_")
    os.environ["MISSIONS_WORKSPACE_DIR"] = dossier.name
    lp.get_fallback_llms = lambda *_a, **_k: []
    mn.dispatch_tool = _dispatch
    try:
        async with throwaway_user("bench_z") as uid:
            m = await mission_service.create_mission(
                user_id=uid, title="Bench Z", goal=_BUT, budget_iterations=3,
            )
            await mission_service.start_mission(m.id)

            # ── Passage 1 : deux outils dans le MÊME fil, puis « à suivre ».
            premier = _ModeleScripte([
                _appel("web_search", query="imprimeries Lyon"),
                _appel("sheets_append_row", values=["PUBLIGIFTS"]),
                _texte(
                    "PUBLIGIFTS relevée et ajoutée au tableur. Il reste IMPRIM2 "
                    f"et TROISIEME. {MARQUEUR_A_SUIVRE}"
                ),
            ])
            lp.get_llm_for_tier = lambda *_a, **_k: premier
            r1 = await run_mission_chat_passage(m.id, uid, _BUT)

            outils_p1 = [e["tool"] for e in journal]
            apres_p1 = await mission_service.get_mission(m.id)

            # ── Passage 2 : le budget (3) ne laisse plus qu'UNE action.
            second = _ModeleScripte([
                _appel("sheets_append_row", values=["IMPRIM2"]),
                _appel("sheets_append_row", values=["TROISIEME"]),
                _texte("Les trois imprimeries sont dans le tableur."),
            ])
            lp.get_llm_for_tier = lambda *_a, **_k: second
            r2 = await run_mission_chat_passage(m.id, uid, _BUT)

            ouverture = second.prompts[0] if second.prompts else ""
            refus = second.prompts[-1] if second.prompts else ""
            steps = await mission_service.list_steps(m.id)
    finally:
        lp.get_llm_for_tier = orig["tier"]
        lp.get_fallback_llms = orig["fallbacks"]
        mn.dispatch_tool = orig["dispatch"]
        if orig["ws"] is None:
            os.environ.pop("MISSIONS_WORKSPACE_DIR", None)
        else:
            os.environ["MISSIONS_WORKSPACE_DIR"] = orig["ws"]
        dossier.cleanup()

    actes = [s for s in steps if s.phase == "act"]
    checks = {
        # Un passage = un seul fil : deux outils enchaînés, pas un par tick.
        "le_passage_enchaine_ses_outils": outils_p1 == [
            "web_search", "sheets_append_row",
        ],
        # La passerelle des missions reçoit l'identité de la mission — sans
        # elle, le mandat ne peut pas mordre.
        "la_passerelle_recoit_la_mission": all(
            e["mission_id"] == m.id for e in journal
        ),
        # Le modèle a demandé un passage de plus : on ne clôt pas.
        "le_premier_passage_ne_clot_pas": r1.get("done") is False,
        # Le carnet est la mémoire entre deux réveils.
        "le_second_reveil_relit_le_carnet": "PUBLIGIFTS" in ouverture,
        "le_carnet_nomme_les_actions_faites": "web_search" in ouverture,
        # Le budget mord AU MILIEU du passage, et le modèle l'apprend.
        "le_budget_coupe_le_second_appel": len(journal) == 3,
        "le_refus_est_nomme_au_modele": "budget" in refus.lower(),
        # Et la mission se termine sur une conclusion non vide.
        "la_mission_se_termine": r2.get("done") is True,
        "le_resume_est_livre": bool(r2.get("final_summary")),
        "le_marqueur_ne_fuit_pas_dans_le_resume":
            MARQUEUR_A_SUIVRE not in (r2.get("final_summary") or ""),
        # Les actions restent auditables et comptent pour le budget.
        "les_actions_sont_tracees": len(actes) == 3,
        "les_iterations_sont_comptees": (apres_p1.iterations_used or 0) == 2,
    }
    return from_checks(
        checks,
        outils_passage_1=outils_p1,
        actions_totales=len(journal),
        resume=(r2.get("final_summary") or "")[:200],
    )
