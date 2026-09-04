# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_mission_choisit_ses_familles_d_outils.py
# @brief      Une mission choisit ses FAMILLES d'outils une fois, au premier
#             passage, avec le petit modèle local ; chaque action ne porte
#             plus que ces familles et le noyau, pas les 227 outils.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « Nettoyage mails », 04/09/2026 : 118 actions, 5 M tokens pour
trois mails, à ~45 000 tokens l'action — le catalogue complet (227 outils)
dans chaque prompt.

Mesuré la veille sur les traces des missions passées : le sélecteur outil
par outil manque `gmail_raw_api_call`, `session_todo`, `web_search`… ;
par FAMILLES (le préfixe du nom : `gmail_`, `contacts_`…) plus un noyau
fixe, il ne manque rien — 36 outils pour les mails, 75 pour la
prospection, contre 227.

Règles :
1. la sélection se fait UNE fois, au premier passage, et se lit ensuite
   dans le workspace (`OUTILS.json`) : le prompt reste stable entre passages ;
2. le sélecteur qui doute rend tout : aucune restriction, comme aujourd'hui ;
3. `find_tool` reste le filet : un outil découvert entre dans la sélection
   avec toute sa famille, pour le reste de la mission.
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool


def _outil(nom: str):
    return StructuredTool.from_function(
        func=lambda x="": "ok", name=nom, description=f"Outil de test {nom}.",
    )


_CATALOGUE = [_outil(n) for n in (
    "gmail_list_emails", "gmail_raw_api_call", "gmail_trash_emails",
    "contacts_list", "contacts_search",
    "browser_open_tab", "browser_click",
    "sheets_append_row",
    "find_tool", "report_missing_capability", "session_todo", "web_search",
    "web_fetch_page", "memory_recall", "search_past_conversations_tool",
)]


# ── 1. Familles + noyau ──────────────────────────────────────────────────────

def test_la_famille_est_le_prefixe_du_nom():
    from app.agent.missions.outillage import famille

    assert famille("gmail_raw_api_call") == "gmail"
    assert famille("browser_tab_read_text") == "browser"
    assert famille("delegate") == "delegate"


@pytest.mark.asyncio
async def test_les_familles_des_outils_choisis_et_le_noyau(monkeypatch):
    from app.agent.missions import outillage

    async def _selecteur(goal, tools, *, include_core=True):
        return [t for t in tools if t.name in ("gmail_raw_api_call", "contacts_search")]

    monkeypatch.setattr(outillage, "select_tools", _selecteur)

    choix = await outillage.choisir_l_outillage("Nettoie mes mails", _CATALOGUE)

    assert choix is not None
    assert choix.familles == ["contacts", "gmail"]
    assert {"gmail_list_emails", "gmail_trash_emails", "contacts_list"} <= set(choix.outils)
    assert set(outillage.NOYAU_MISSION) <= set(choix.outils)
    assert "web_fetch_page" in choix.outils, "la famille web fait partie du noyau"
    assert not {"browser_open_tab", "sheets_append_row"} & set(choix.outils)


@pytest.mark.asyncio
async def test_un_selecteur_qui_doute_ne_restreint_rien(monkeypatch):
    """`select_tools` rend la liste COMPLÈTE quand il n'a pas de modèle ou
    ne reconnaît rien : la mission garde tout le catalogue."""
    from app.agent.missions import outillage

    async def _selecteur(goal, tools, *, include_core=True):
        return list(tools)

    monkeypatch.setattr(outillage, "select_tools", _selecteur)

    assert await outillage.choisir_l_outillage("Nettoie mes mails", _CATALOGUE) is None


# ── 2. Une fois par mission, dans le workspace ───────────────────────────────

@pytest.mark.asyncio
async def test_la_selection_se_fait_une_fois_et_se_relit(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.agent.missions import outillage
    from app.services.mission_workspace import read_carnet, workspace_dir

    appels = {"n": 0}

    async def _selecteur(goal, tools, *, include_core=True):
        appels["n"] += 1
        return [t for t in tools if t.name == "gmail_trash_emails"]

    monkeypatch.setattr(outillage, "select_tools", _selecteur)
    mid = str(uuid.uuid4())

    premier = await outillage.outillage_de_la_mission(mid, "Nettoie mes mails", _CATALOGUE)
    second = await outillage.outillage_de_la_mission(mid, "Nettoie mes mails", _CATALOGUE)

    assert appels["n"] == 1
    assert premier == second
    assert "gmail_raw_api_call" in premier
    fichier = json.loads((workspace_dir(mid) / "OUTILS.json").read_text())
    assert fichier["familles"] == ["gmail"]
    assert "## Outils" in (read_carnet(mid) or "")
    assert "gmail" in (read_carnet(mid) or "")


@pytest.mark.asyncio
async def test_un_outil_decouvert_elargit_la_selection_a_sa_famille(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.agent.missions import outillage

    async def _selecteur(goal, tools, *, include_core=True):
        return [t for t in tools if t.name == "gmail_trash_emails"]

    monkeypatch.setattr(outillage, "select_tools", _selecteur)
    mid = str(uuid.uuid4())
    avant = await outillage.outillage_de_la_mission(mid, "Nettoie mes mails", _CATALOGUE)
    assert "sheets_append_row" not in avant

    apres = outillage.elargir(mid, ["sheets_append_row"], _CATALOGUE)

    assert "sheets_append_row" in apres
    assert set(avant) <= set(apres)
    relu = await outillage.outillage_de_la_mission(mid, "Nettoie mes mails", _CATALOGUE)
    assert "sheets_append_row" in relu


# ── 3. Le passage ne branche que la sélection ───────────────────────────────

_BUT = "Trouve les trois imprimeries les plus proches et note-les dans un tableur."


def _appel(nom: str, **args) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": nom, "args": args, "id": f"call_{nom}_{uuid.uuid4().hex[:4]}"}],
    )


class _ModeleQuiNoteSesOutils:
    def __init__(self, tours):
        self._tours = list(tours)
        self.liaisons: list[set[str]] = []

    def bind_tools(self, tools, **_kw):
        self.liaisons.append({getattr(t, "name", "?") for t in tools})
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        if not self._tours:
            return AIMessage(content="Rien a faire.")
        return self._tours.pop(0)


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_fam_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal=_BUT, budget_iterations=30,
    )
    await mission_service.start_mission(m.id)
    yield uid, m.id
    await purge_user(uid)


@pytest.fixture
def catalogue_de_test():
    from app.skills import get_skill_registry
    from app.skills.base import Skill

    faux = [_outil(f"zzz_outil_{i:02d}") for i in range(25)]
    faux += [_outil("sheets_ajoute_une_ligne"), _outil("sheets_lit_une_plage")]
    registre = get_skill_registry()
    registre.register_or_replace(Skill(
        name="_bench_familles", display_name="F", description="F", icon="F", tools=faux,
    ))
    yield
    registre.unregister("_bench_familles")


def _branche(monkeypatch, modele, dispatch):
    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp

    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(lp, "get_llm", lambda *a, **k: modele, raising=False)
    monkeypatch.setattr(mn, "dispatch_tool", dispatch)


@pytest.mark.asyncio
async def test_le_passage_ne_branche_que_les_familles_choisies(
    mission, catalogue_de_test, monkeypatch,
):
    uid, mid = mission
    from app.agent.missions import outillage

    async def _selecteur(goal, tools, *, include_core=True):
        return [t for t in tools if t.name == "sheets_ajoute_une_ligne"]

    monkeypatch.setattr(outillage, "select_tools", _selecteur)

    async def _dispatch(nom, args, _cid, _uid, **_kw):
        return "ok", True

    modele = _ModeleQuiNoteSesOutils([AIMessage(content="Rien a faire.")])
    _branche(monkeypatch, modele, _dispatch)
    from app.agent.missions.chat_loop import run_mission_chat_passage

    await run_mission_chat_passage(mid, uid, _BUT)

    from app.skills import get_skill_registry

    lies = modele.liaisons[0]
    assert {"sheets_ajoute_une_ligne", "sheets_lit_une_plage"} <= lies
    # Le noyau : ce qui en existe dans le registre de test est branché.
    noyau_present = {t.name for t in get_skill_registry().all_tools} & set(outillage.NOYAU_MISSION)
    assert noyau_present <= lies, noyau_present - lies
    assert "zzz_outil_00" not in lies, "le catalogue complet est encore branché"


@pytest.mark.asyncio
async def test_un_outil_trouve_par_find_tool_est_branche_au_tour_suivant(
    mission, catalogue_de_test, monkeypatch,
):
    uid, mid = mission
    from app.agent.discovered_tools import add_discovered
    from app.agent.missions import outillage

    async def _selecteur(goal, tools, *, include_core=True):
        return [t for t in tools if t.name == "sheets_ajoute_une_ligne"]

    monkeypatch.setattr(outillage, "select_tools", _selecteur)

    async def _dispatch(nom, args, _cid, _uid, **_kw):
        if nom == "find_tool":
            add_discovered(mid, ["zzz_outil_05"])
            return "Outils trouvés : zzz_outil_05", True
        return "ok", True

    modele = _ModeleQuiNoteSesOutils([
        _appel("find_tool", capability="un outil zzz"),
        AIMessage(content="Rien a faire."),
    ])
    _branche(monkeypatch, modele, _dispatch)
    from app.agent.missions.chat_loop import run_mission_chat_passage

    await run_mission_chat_passage(mid, uid, _BUT)

    assert "zzz_outil_05" not in modele.liaisons[0]
    assert "zzz_outil_05" in modele.liaisons[1]
    assert "zzz_outil_00" in modele.liaisons[1], "la famille de l'outil découvert n'est pas entrée"
