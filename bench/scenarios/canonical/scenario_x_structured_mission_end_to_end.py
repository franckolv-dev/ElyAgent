# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_x_structured_mission_end_to_end.py
# @brief      Une mission STRUCTUREE complete, du plan au resume final :
#             spec avec `tools:` et `foreach`, plusieurs ticks du vrai
#             graphe, une etape qui echoue, une qui reussit.
# @license    Elastic License 2.0
# =============================================================================
"""Scénario X — la chaîne mission de bout en bout (29/08/2026).

POURQUOI CE SCÉNARIO EXISTE
---------------------------
Six défauts du chemin « mission structurée » ont été trouvés en deux jours,
un par un, EN PRODUCTION, par l'utilisateur :

  1. `sheets_create_spreadsheet` écrivait dans `Sheet1!A1` — HTTP 400 sur
     tout compte Google non anglophone, tableur créé mais vide ;
  2. les outils de l'étape n'étaient pas liés (`sheets_batch_update`
     proposé là où il fallait `sheets_create_spreadsheet`) ;
  3. ce que `find_tool` surface n'était pas rebindé au tick suivant ;
  4. une spec ne pouvait pas nommer ses outils (`tool_hint` à None en dur) ;
  5. la source d'un `foreach` était le contexte général tronqué, pas la
     sortie de l'étape nommée ;
  6. la date du jour n'était donnée à personne sur une spec.

Chacun avait ses tests unitaires verts. Le harnais comptait 3 893 tests et
51 scénarios de bench — et pas UN qui fasse tourner une mission structurée
du plan au résumé. Chaque composant était vérifié isolément ; la chaîne,
jamais.

Ce scénario ferme ce trou. Il exerce le VRAI graphe de mission sur
plusieurs ticks, avec le LLM et les outils Google simulés — donc hermétique
et rapide — et vérifie ce qu'aucun test unitaire ne pouvait voir : que les
morceaux, mis bout à bout, produisent le livrable attendu.

CE QU'IL COUVRE
---------------
- le plan vient de la spec, sans appel au planificateur ;
- l'étape reçoit l'outil que sa spec NOMME (défauts 2 et 4) ;
- l'acteur connaît la date du jour (défaut 6) ;
- le `foreach` s'étend depuis la sortie de l'étape qu'il nomme (défaut 5) ;
- chaque item est traité, et le livrable contient une ligne par item ;
- une étape qui échoue est abandonnée après ses tentatives, sans bloquer ;
- le résumé final AVOUE l'étape abandonnée.
"""
from __future__ import annotations

import json
import types
from datetime import datetime
from zoneinfo import ZoneInfo

NAME = "X — mission structurée de bout en bout"
DESCRIPTION = (
    "Une spec (tools + foreach + handler) traversée par le vrai graphe sur "
    "plusieurs ticks, LLM et outils Google simulés : le foreach s'étend "
    "depuis l'étape nommée, chaque item écrit sa ligne, l'étape en échec "
    "est abandonnée et le résumé final le dit."
)
TAGS = ["medium"]

_SPEC = """
version: 1
steps:
  - id: historique
    do: "Cherche le fichier historique.md et lis-le. S'il n'existe pas, crée-le vide."
    tools: [drive_list_files, drive_create_file]

  - id: societes
    do: "Cherche des sociétés et rends leurs noms, un par ligne."
    tools: [web_search]

  - id: tableur
    do: "Crée le Google Sheet du jour avec ses en-têtes."
    tools: [sheets_create_spreadsheet]

  - id: contacts
    foreach: "{{ societes.output }}"
    do: "Pour {{ item }}, relève le contact et ajoute une ligne au tableur."
    tools: [sheets_append_rows]
    on_error: resume_next

  - id: memoire
    do: "Consigne les sociétés retenues dans l'historique."
    tools: [drive_update_file]
""".strip()

# Ce que la recherche « rend » — deux sociétés, une par ligne.
_SOURCE_SOCIETES = "Résultats :\nACME Négoce\nGamma Distribution"


def _jour_et_annee() -> tuple[str, str]:
    """Jour et année d'aujourd'hui, à Paris.

    On ne compare PAS à un format figé : `_current_date_paris_str` est
    libre de sa mise en forme. Ce qui doit être vrai, c'est que l'acteur
    écrive la date DU JOUR — pas celle qu'il invente (« 2025_05_22 »).
    """
    maintenant = datetime.now(ZoneInfo("Europe/Paris"))
    return str(maintenant.day), str(maintenant.year)


class _FakeLLM:
    """Acteur, évaluateur et extracteur foreach, selon le prompt reçu.

    Un seul faux modèle sert les trois rôles : c'est ce que fait la vraie
    chaîne, qui les distingue par le prompt et non par le client.
    """

    def __init__(self, journal: dict):
        self._j = journal

    async def ainvoke(self, messages, **_kw):
        texte = _prompt_text(messages)

        # 1. Extraction des items d'un foreach.
        if "Extrais la LISTE des items" in texte:
            self._j["expand_source_len"] = _source_len(texte)
            return types.SimpleNamespace(
                content=json.dumps(["ACME Négoce", "Gamma Distribution"])
            )

        # 2. Évaluation d'une action.
        if "success" in texte and "all_done" in texte:
            dernier = self._j.get("dernier_outil")
            # L'étape composée : chercher ne l'accomplit pas, mais fait
            # avancer. C'est le verdict que l'évaluateur ne savait pas
            # rendre — il validait la recherche et le fichier n'était
            # jamais créé (30/08/2026).
            if dernier == "drive_list_files":
                return types.SimpleNamespace(content=json.dumps({
                    "success": False, "progress": True,
                    "reason": "fichier absent, il reste à le créer",
                    "all_done": False,
                }))
            echec = dernier == "drive_update_file"
            return types.SimpleNamespace(content=json.dumps({
                "success": not echec,
                "reason": "consignation impossible" if echec else "fait",
                "all_done": False,
            }))

        # 3. Acteur : il choisit un outil. On note ce qu'il a REÇU.
        self._j.setdefault("prompts_acteur", []).append(texte)
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


def _source_len(prompt: str) -> int:
    """Taille du bloc « son résultat » du prompt d'expansion."""
    debut = prompt.find("son résultat :")
    if debut < 0:
        return 0
    fin = prompt.find("Étape à itérer", debut)
    return len(prompt[debut + len("son résultat :"):fin].strip())


def _etape_courante(prompt: str) -> str:
    """La seule ligne qui décrit l'étape À FAIRE maintenant.

    Le prompt reprend le plan ENTIER : matcher sur tout le texte ferait
    reconnaître la première étape à chaque tour.
    """
    marqueur = "Étape courante à exécuter : «"
    i = prompt.find(marqueur)
    if i < 0:
        return prompt
    return prompt[i + len(marqueur):].split("»")[0]


def _tool_call_for(prompt: str, journal: dict) -> list[dict]:
    """L'outil que l'acteur émet, selon l'étape COURANTE."""
    etape = _etape_courante(prompt)
    def _call(nom, args):
        journal["dernier_outil"] = nom
        return [{"name": nom, "args": args, "id": f"call_{nom}"}]

    if "historique.md" in etape:
        # Deux actes, comme dans la vraie mission : on cherche, on ne
        # trouve pas, puis on crée. Le second n'arrive que si le premier
        # n'a pas consommé le droit à l'erreur de l'étape.
        if not journal.get("historique_cherche"):
            journal["historique_cherche"] = True
            return _call("drive_list_files", {"query": "historique.md"})
        return _call("drive_create_file", {"name": "historique.md",
                                           "content": ""})
    if "rends leurs noms" in etape:
        return _call("web_search", {"query": "sociétés de négoce"})
    if "Crée le Google Sheet" in etape:
        # La date vient du prompt — c'est le défaut 6 qu'on vérifie.
        return _call("sheets_create_spreadsheet", {
            "title": f"prospection-{_date_du_prompt(prompt)}",
            "headers": ["Société", "Contact"],
        })
    if "relève le contact" in etape:
        item = _item_du_prompt(etape)
        return _call("sheets_append_rows", {
            "spreadsheet_id": "ss-bench", "rows": [[item, "Contact " + item]],
        })
    return _call("drive_update_file", {"file_id": "hist", "content": "x"})


def _date_du_prompt(prompt: str) -> str:
    """La date que l'acteur LIT dans son prompt système, ou une balise."""
    marqueur = "Date du jour :"
    i = prompt.find(marqueur)
    if i < 0:
        return "DATE_ABSENTE_DU_PROMPT"
    return prompt[i + len(marqueur):].strip().split(" (")[0].strip()


def _item_du_prompt(prompt: str) -> str:
    i = prompt.find("Pour ")
    return prompt[i + 5:].split(",")[0].strip() if i >= 0 else "?"


async def run() -> dict:
    from langgraph.checkpoint.memory import MemorySaver

    from app.agent.missions.graph import build_mission_graph
    from app.services import mission_service, mission_spec_runtime as msr
    from bench.scenarios._base import from_checks, throwaway_user

    from app.skills.builtin import register_all

    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp

    # Le registre n'est peuplé qu'au démarrage de l'app. Sans lui, la
    # sélection d'outils travaille sur un catalogue vide : elle « passe »
    # sans rien prouver.
    register_all()

    journal: dict = {"lignes_ecrites": []}
    faux = _FakeLLM(journal)

    # ── Simulation : LLM (3 rôles) + outils Google ──────────────────
    orig = {
        "eval": mn._get_evaluator_llm,
        "tier": lp.get_llm_for_tier,
        "fallbacks": lp.get_fallback_llms,
        "dispatch": mn.dispatch_tool,
    }

    async def _dispatch(tool_name, tool_args, _cid, _uid, **_kw):
        """Les outils rendent ce que rendrait Google, sans réseau."""
        if tool_name == "drive_list_files":
            return "Aucun fichier trouvé.", True
        if tool_name == "drive_create_file":
            journal["historique_cree"] = tool_args.get("name")
            return "Fichier créé : historique.md", True
        if tool_name == "web_search":
            return _SOURCE_SOCIETES, True
        if tool_name == "sheets_create_spreadsheet":
            journal["titre_tableur"] = tool_args.get("title", "")
            return f"Feuille créée : '{tool_args.get('title')}' ID : ss-bench", True
        if tool_name == "sheets_append_rows":
            journal["lignes_ecrites"].extend(tool_args.get("rows") or [])
            return "1 ligne(s) ajoutée(s)", True
        # drive_update_file échoue : c'est l'étape qu'on veut voir abandonnée.
        return "Erreur Drive : fichier introuvable", False

    # On ne remplace QUE la tête LLM : `_get_actor_llms` continue de tourner,
    # donc la vraie sélection d'outils est exercée — c'est elle qui portait
    # les défauts 2 et 4.
    mn._get_evaluator_llm = lambda **_kw: faux
    lp.get_llm_for_tier = lambda _t: faux
    lp.get_fallback_llms = lambda: []
    msr.get_llm_for_tier = lambda _t: faux
    mn.dispatch_tool = _dispatch
    try:
        async with throwaway_user("bench_x") as uid:
            m = await mission_service.create_mission(
                user_id=uid, title="Bench X", goal="prospecter",
                spec_yaml=_SPEC,
            )
            # Checkpointer EN MÉMOIRE, pas le singleton SQLite global : un
            # scénario de bench doit être hermétique et ne pas dépendre d'un
            # état partagé avec les autres. Ce qu'on vérifie ici est que
            # l'état SURVIT d'un tick à l'autre (compteurs, plan_json) — la
            # persistance sur disque relève d'un autre test.
            graph = build_mission_graph().compile(checkpointer=MemorySaver())
            config = {"configurable": {"thread_id": m.id}}
            etat: dict = {}
            # Assez de ticks pour : l'étape composée (2 actes) + 2 étapes
            # simples + 2 items + memoire (2 tentatives) + la terminaison.
            # Le graphe sort à chaque tick.
            for _ in range(14):
                etat = await graph.ainvoke(
                    {"mission_id": m.id, "user_id": uid, "goal": "prospecter"},
                    config=config,
                )
                if etat.get("done") or etat.get("failed"):
                    break

            runs = await msr.list_step_runs(m.id)
    finally:
        mn._get_evaluator_llm = orig["eval"]
        lp.get_llm_for_tier = orig["tier"]
        lp.get_fallback_llms = orig["fallbacks"]
        mn.dispatch_tool = orig["dispatch"]

    par_step = {}
    for r in runs:
        par_step.setdefault(r.step_id, []).append(r)
    items_contacts = [r.item_value for r in par_step.get("contacts", []) if r.item_value]
    resume = etat.get("final_summary") or ""
    outils_lies = journal.get("outils_lies") or []
    noms_lies = {n for lot in outils_lies for n in lot}

    checks = {
        # Le plan vient de la spec, pas du planificateur.
        "plan_depuis_la_spec": bool((etat.get("plan_json") or {}).get("from_spec")),
        # Défauts 2 et 4 : l'étape reçoit l'outil que sa spec NOMME.
        # Le témoin est `drive_update_file` : rien dans « Consigne les
        # sociétés retenues dans l'historique » ne le suggère, donc les
        # heuristiques ne peuvent pas le trouver toutes seules. Le vérifier
        # sur `sheets_create_spreadsheet` ne prouverait rien — « Google
        # Sheet » est dans sa description, la sélection le trouve sans la
        # spec.
        "outil_nomme_par_la_spec_lie": "drive_update_file" in noms_lies,
        # Défaut 7 (30/08) : une étape qui demande DEUX actes va au bout.
        # L'évaluateur validait le premier — « la recherche a correctement
        # rapporté l'absence du fichier » — et le fichier n'était jamais
        # créé. Rendre le verdict exigeant sans l'état « ça avance »
        # l'aurait abandonnée à mi-chemin : MAX_STEP_ATTEMPTS vaut 2.
        "etape_composee_va_au_bout": journal.get("historique_cree") == "historique.md",
        "etape_composee_garde_son_droit_a_l_erreur": all(
            r.status == "done" and r.attempts <= 1
            for r in par_step.get("historique", [])
        ),
        # Défaut 6 : l'acteur connaît la date — sinon il l'invente.
        "acteur_connait_la_date": all(
            frag in (journal.get("titre_tableur") or "")
            for frag in _jour_et_annee()
        ),
        # Défaut 5 : le foreach s'étend depuis la sortie de l'étape nommée.
        "foreach_etendu_en_items": len(items_contacts) == 2,
        "source_du_foreach_non_vide": journal.get("expand_source_len", 0) > 0,
        # La chaîne produit le livrable : une ligne par item.
        "une_ligne_par_item": len(journal["lignes_ecrites"]) == 2,
        "lignes_portent_les_items": {r[0] for r in journal["lignes_ecrites"]}
        == {"ACME Négoce", "Gamma Distribution"},
        # Une étape qui échoue est abandonnée, elle ne bloque pas la mission.
        "etape_en_echec_abandonnee": any(
            r.status == "skipped" for r in par_step.get("memoire", [])
        ),
        "mission_terminee": bool(etat.get("done")),
        # Et le résumé final le DIT — pas de succès de façade.
        "resume_avoue_l_abandon": "abandonn" in resume.lower(),
    }
    return from_checks(
        checks,
        items=items_contacts,
        titre_tableur=journal.get("titre_tableur"),
        lignes=len(journal["lignes_ecrites"]),
        resume=resume[:200],
    )
