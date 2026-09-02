# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_le_passage_tient_le_vault_et_le_carnet.py
# @brief      Troisieme relecture adverse du lot « la fuite du prompt
#             systeme » (02/09/2026) : un seul vault PII par mission, un
#             passage annule laisse une trace, un passage mort n'invente pas
#             de ligne de cout.
# @license    Elastic License 2.0
# =============================================================================
"""Ce qui SURVIT aux deux premieres passes sur `missions/chat_loop.py`.

1. LE SECOND VAULT (grave)
   `nodes.prompt_systeme_sortant` anonymise le prompt systeme avec le filtre
   que l'APPELANT pose dans `FILTRE_PII_DU_TOUR`. Le passage de mission ne le
   posait pas — les deux docstrings affirmaient pourtant qu'il le faisait. Le
   repli ouvrait donc `get_filter(<mission_id>)`, un SECOND vault a cote de
   `mission_filter()` = `get_filter("mission:<id>")`. Mesure du 02/09 sur un
   passage reel : `[EMAIL_0]` valait `nom@domaine.tld` dans le vault d'ombre
   et `jean.dupont@exemple.fr` dans celui de la mission. Le modele lit les
   deux dans le MEME prompt, et `deanonymize_any` — qui n'interroge que le
   filtre de la mission — resout le placeholder d'ombre vers la MAUVAISE
   adresse, dans le carnet comme dans le resume rendu a l'utilisateur.

2. `asyncio.CancelledError` DERIVE DE `BaseException`
   Le `except Exception` du passage ne la voit pas : le carnet n'est pas
   ecrit. Le heartbeat joue les passages en tache de fond et la boucle annule
   les taches en vol a l'arret du processus. Un `docker compose up -d`
   pendant un passage rejouait donc exactement le defaut que ce module existe
   pour fermer : le reveil suivant refait les actions deja faites.

3. LA LIGNE DE COUT FANTOME
   Un passage tue par un 429 laisse `resultat` vide : `record_turn_usage`
   ecrivait quand meme `0 in / 0 out / provider='unknown'`. Or le noeud
   d'outils a DEJA vu l'etat — messages et `model_used` — du tour precedent.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage

_BUT = "Note les trois imprimeries les plus proches dans un tableur."
_EMAIL = "jean.dupont@exemple.fr"
_TEL = "06 12 34 56 78"


# ── Les doubles ──────────────────────────────────────────────────────────────


def _appel(nom: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": nom, "args": args, "id": f"call_{nom}_{uuid.uuid4().hex[:4]}"},
    ])


class _ModeleCloud:
    """Le modele du tier COMPLEX : cloud, et il joue le script dans l'ordre.

    Une entree qui est une exception est LEVEE — y compris une
    `BaseException` comme `CancelledError`, que le passage doit voir."""

    model_name = "glm-4.6"

    def __init__(self, tours=None):
        self._tours = list(tours or [])
        self.prompts: list[str] = []

    def bind_tools(self, tools, **_kw):
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        morceaux = []
        for m in messages or ():
            c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            morceaux.append(c if isinstance(c, str) else str(c))
        self.prompts.append("\n".join(morceaux))
        if "Tu vérifies qu'un travail répond à la demande" in self.prompts[-1]:
            return AIMessage(content="CONFORME")
        if not self._tours:
            return AIMessage(content="Rien de plus.")
        tour = self._tours.pop(0)
        if isinstance(tour, BaseException):
            raise tour
        return tour


def _branche(monkeypatch, modele, dispatch=None):
    """Le decor de Franck : tier COMPLEX cloud, replis coupes."""
    import app.agent.missions.nodes as mnodes
    import app.services.llm_provider as lp

    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)
    if dispatch is not None:
        monkeypatch.setattr(mnodes, "dispatch_tool", dispatch)


def _dispatch_qui_marche(joues: list, tokens: int = 0):
    async def _d(nom, args, cid, user_id, user_request=None, mission_id=None):
        joues.append(nom)
        return f"{nom} ok", True
    return _d


# ── Le decor ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.models.user_memory import UserProfile
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_vault_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        db.add(UserProfile(user_id=uid, key="primary_email", value=_EMAIL,
                           confidence=1.0, source_count=9))
        db.add(UserProfile(user_id=uid, key="strict_rules",
                           value=f"Toujours me joindre au {_TEL}.",
                           confidence=1.0, source_count=9))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal=_BUT, budget_iterations=30,
    )
    await mission_service.start_mission(m.id)
    yield uid, m.id
    await purge_user(uid)


# ── 1. Un seul vault PII par mission ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_passage_pose_le_filtre_pii_de_la_mission(mission, monkeypatch):
    """`prompt_systeme_sortant` doit trouver le filtre de CETTE mission.

    Sans la ContextVar, il se rabat sur `get_filter(conversation_id)` et
    fabrique un vault parallele."""
    uid, mid = mission
    modele = _ModeleCloud([AIMessage(content="Fait.")])
    _branche(monkeypatch, modele)

    import app.agent.nodes as nodes

    vus: list = []
    _vrai = nodes.prompt_systeme_sortant

    def _espion(system, llm, conv):
        vus.append(nodes.FILTRE_PII_DU_TOUR.get())
        return _vrai(system, llm, conv)

    monkeypatch.setattr(nodes, "prompt_systeme_sortant", _espion)

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.agent.missions.pii import mission_filter

    await run_mission_chat_passage(mid, uid, _BUT)

    assert vus, "la frontiere d'envoi n'a pas ete franchie : le test ne prouve rien"
    attendu = mission_filter(mid)
    assert all(f is attendu for f in vus), (
        "le passage n'a pas pose FILTRE_PII_DU_TOUR : le prompt systeme est "
        f"anonymise par un AUTRE filtre que celui de la mission ({vus})"
    )


@pytest.mark.asyncio
async def test_aucun_vault_dombre_nest_ouvert_sur_la_mission(mission, monkeypatch):
    """Deux vaults sur la meme mission = `[EMAIL_0]` a deux sens.

    Le placeholder d'ombre ne se resout pas dans le filtre de la mission —
    ou pire, s'y resout vers la valeur de quelqu'un d'autre."""
    uid, mid = mission
    modele = _ModeleCloud([AIMessage(content="Fait.")])
    _branche(monkeypatch, modele)

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import conversation_filters

    await run_mission_chat_passage(mid, uid, _BUT)

    ombre = conversation_filters.get_filter(mid)._vault
    assert not ombre, (
        f"un SECOND vault s'est ouvert sur la mission : {ombre} — ses "
        "placeholders sont irresolubles a la sortie, ou resolus vers la "
        "mauvaise valeur"
    )


# ── 2. Un passage annule laisse une trace ────────────────────────────────────


@pytest.mark.asyncio
async def test_un_passage_annule_est_consigne_au_carnet(mission, monkeypatch):
    """`CancelledError` derive de `BaseException` : `except Exception` ne la
    voit pas. A l'arret du processus, le carnet restait muet sur des actions
    DEJA jouees, et le reveil suivant les rejouait."""
    uid, mid = mission
    joues: list = []
    modele = _ModeleCloud([
        _appel("drive_create_folder", name="Prospection"),
        asyncio.CancelledError(),
    ])
    _branche(monkeypatch, modele, _dispatch_qui_marche(joues))

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services.mission_workspace import read_carnet

    with pytest.raises(asyncio.CancelledError):
        await run_mission_chat_passage(mid, uid, _BUT)

    assert joues == ["drive_create_folder"]
    carnet = read_carnet(mid) or ""
    assert "drive_create_folder" in carnet, (
        "le dossier a ete cree puis le passage annule : sans cette ligne, le "
        "reveil suivant le recree"
    )
    assert "INTERROMPU" in carnet, "la ligne doit DIRE que le passage a ete coupe"
    assert "annul" in carnet.lower(), "et POURQUOI"


# ── 3. Pas de ligne de cout fantome ──────────────────────────────────────────


async def _lignes_dusage(uid: str) -> list:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.usage_log import UsageLog

    async with async_session() as db:
        return list((await db.execute(
            select(UsageLog).where(UsageLog.user_id == uid)
        )).scalars().all())


@pytest.mark.asyncio
async def test_un_passage_mort_avant_tout_appel_necrit_pas_de_ligne_fantome(
    mission, monkeypatch,
):
    """Rien a attribuer : `provider='unknown'`, `0 in / 0 out`. Une ligne
    pareille ne mesure rien et pollue la ventilation par fournisseur."""
    uid, mid = mission
    modele = _ModeleCloud([RuntimeError("Provider returned error, code 429")])
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))

    from app.agent.missions.chat_loop import run_mission_chat_passage

    with pytest.raises(RuntimeError, match="429"):
        await run_mission_chat_passage(mid, uid, _BUT)

    fantomes = [
        r for r in await _lignes_dusage(uid)
        if (r.provider or "") == "unknown"
        and not (r.input_tokens or 0) and not (r.output_tokens or 0)
    ]
    assert not fantomes, (
        f"{len(fantomes)} ligne(s) « unknown » a cout nul ecrite(s) par un "
        "passage qui n'a jamais rien mesure"
    )


@pytest.mark.asyncio
async def test_un_passage_tue_en_vol_attribue_quand_meme_ce_quil_a_depense(
    mission, monkeypatch,
):
    """Le noeud d'outils a DEJA vu l'etat — messages et `model_used`. Un 429
    au second tour ne doit pas effacer le cout du premier."""
    uid, mid = mission
    premier = _appel("web_search", query="imprimeries")
    premier.usage_metadata = {
        "input_tokens": 1200, "output_tokens": 40, "total_tokens": 1240,
    }
    modele = _ModeleCloud([premier, RuntimeError("Provider returned error, code 429")])
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import mission_service

    with pytest.raises(RuntimeError, match="429"):
        await run_mission_chat_passage(mid, uid, _BUT)

    m = await mission_service.get_mission(mid)
    assert (m.tokens_used or 0) >= 1240, (
        "les 1 240 tokens du premier tour ont disparu : le budget de la "
        "mission ne mordra jamais sur un passage qui plante"
    )
    lignes = await _lignes_dusage(uid)
    assert any((r.input_tokens or 0) >= 1200 for r in lignes), (
        "le cout reellement depense avant le 429 n'a ete attribue nulle part"
    )


@pytest.mark.asyncio
async def test_le_dernier_tour_dagent_est_compte_lui_aussi(mission, monkeypatch):
    """⚠️ 02/09/2026 — le tour le plus CHER etait celui qui echappait.

    Le carnet de secours du cout n'etait pose que dans le noeud `tools`, qui
    photographie l'etat AVANT de lancer les outils. Il ne portait donc jamais
    le tour d'agent qui SUIT le dernier appel d'outil — et c'est celui qui
    porte la reponse complete, donc le gros de la facture.

    Le chemin n'a rien d'exotique : c'est la boucle de conformite, la raison
    d'etre de ce module. `verify` rend « ECARTS : ... », l'agent repart pour
    corriger, et c'est LA que le 429 tombe. Mesure d'origine : 110 tokens
    attribues sur 5 310 factures, soit 2 %.
    """
    uid, mid = mission
    premier = _appel("web_search", query="imprimeries")
    premier.usage_metadata = {
        "input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
    }
    # Le tour d'apres l'outil : la reponse complete, chere, PUIS le 429.
    reponse = AIMessage(content="Voici les trois societes trouvees.")
    reponse.usage_metadata = {
        "input_tokens": 5000, "output_tokens": 200, "total_tokens": 5200,
    }
    modele = _ModeleCloud(
        [premier, reponse, RuntimeError("Provider returned error, code 429")]
    )
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))
    # La conformite renvoie l'agent au travail : c'est ce qui cree un TROISIEME
    # tour, celui qui plante, apres que le deuxieme a deja ete facture.
    # `route_after_conformity` lit le DERNIER message : un HumanMessage qui
    # commence par le marqueur de relance renvoie vers `agent`.
    from langchain_core.messages import HumanMessage as _H

    async def _verify_qui_relance(state):
        return {"messages": [_H(content="[Vérification] ÉCARTS : il manque les URL")]}

    monkeypatch.setattr(
        "app.agent.missions.chat_loop.conformity_node",
        _verify_qui_relance,
        raising=False,
    )

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import mission_service

    with pytest.raises(RuntimeError, match="429"):
        await run_mission_chat_passage(mid, uid, _BUT)

    m = await mission_service.get_mission(mid)
    assert (m.tokens_used or 0) >= 5200, (
        f"seuls {m.tokens_used} tokens attribues : le tour d'agent qui suit "
        f"le dernier appel d'outil n'est pas photographie, et c'est le plus "
        f"cher du passage"
    )
