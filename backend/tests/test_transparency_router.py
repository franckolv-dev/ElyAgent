# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_transparency_router.py
# @brief      Le contrat visible et le registre de sortie disent-ils vrai ?
# @license    MIT
# =============================================================================
"""Deux pages de transparence, deux exigences differentes (audit du 02/09/2026).

Le CONTRAT doit dire ce que le RUNTIME fait, pas ce qu'une table voisine
raconte : un regime d'approbation derive de la mauvaise source est un mensonge
tranquille, invisible en relecture — et celui-la RASSURE.

Le REGISTRE doit rester borne et cloisonne : `usage_logs` grossit (11 280
lignes en production), et une page de transparence qui agregerait toute
l'histoire d'un utilisateur finirait par ne plus repondre — ou par repondre
avec les lignes d'un autre.

⚠️ Ces tests comparent la page a la SOURCE VIVANTE (le manifeste, la
passerelle, les constantes de statut), jamais a une valeur recopiee ici. Une
attente recopiee redivergerait exactement comme le code qu'elle surveille.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI


def _app() -> FastAPI:
    from app.routers.transparency import router

    app = FastAPI()
    app.include_router(router)
    return app


def _fake_user(uid: str):
    """Le handler ne lit que `.id` — inutile de monter une ligne ORM."""

    class _U:
        id = uid

    return _U()


@pytest_asyncio.fixture
async def deux_utilisateurs():
    """Deux comptes reels (les missions portent une FK vers `users.id`).

    Le nettoyage couvre TOUTES les tables filles ecrites par ces tests :
    l'oubli d'une seule empoisonne la suite d'apres (incident CI du 02/09).
    """
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.hitl_preference import HitlPreference
    from app.models.mission import Mission
    from app.models.usage_log import UsageLog
    from app.models.user import User

    await init_db()
    ids = [f"test_tr_{uuid.uuid4().hex[:8]}" for _ in range(2)]
    async with async_session() as db:
        for uid in ids:
            db.add(User(
                id=uid,
                username=f"tr_{uid[-8:]}",
                email=f"{uid}@bench.local",
                hashed_password="x",
            ))
        await db.commit()

    yield ids

    async with async_session() as db:
        for model in (UsageLog, HitlPreference, Mission):
            await db.execute(delete(model).where(model.user_id.in_(ids)))
        await db.execute(delete(User).where(User.id.in_(ids)))
        await db.commit()


async def _log(uid: str, *, provider: str | None, model: str = "m",
               jours: int = 0, tokens: int = 10, skill: str | None = None,
               channel: str = "web", breakdown: str | None = None,
               at: datetime | None = None) -> None:
    from app.database import async_session
    from app.models.usage_log import UsageLog

    async with async_session() as db:
        db.add(UsageLog(
            user_id=uid,
            timestamp=at or datetime.now(timezone.utc) - timedelta(days=jours, minutes=1),
            provider=provider,
            model=model,
            input_tokens=tokens,
            output_tokens=tokens,
            total_tokens=tokens * 2,
            cost_usd=0.0,
            skill_used=skill,
            channel=channel,
            context_breakdown=breakdown,
        ))
        await db.commit()


# ── L'anonyme n'entre pas ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_contrat_sans_jeton_est_refuse() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t",
    ) as client:
        r = await client.get("/api/me/transparency/contract")
    assert r.status_code in (401, 403), r.text


@pytest.mark.asyncio
async def test_le_registre_sans_jeton_est_refuse() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t",
    ) as client:
        r = await client.get("/api/me/transparency/egress")
    assert r.status_code in (401, 403), r.text


# ── Le contrat compte ce que la table dit, pas autre chose ───────────────


@pytest.mark.asyncio
async def test_le_contrat_compte_exactement_les_outils_de_la_table(deux_utilisateurs) -> None:
    from collections import Counter

    from app.agent.tool_nature import TOOL_NATURE
    from app.routers.transparency import visible_contract

    out = await visible_contract(current_user=_fake_user(deux_utilisateurs[0]))

    attendu = Counter(n.effect for n in TOOL_NATURE.values())
    assert out["summary"]["tools"] == len(TOOL_NATURE)
    assert out["summary"]["by_effect"] == dict(attendu)
    # Aucun outil perdu ni compte deux fois par le regroupement en familles.
    listes = [item["name"] for f in out["families"] for item in f["items"]]
    assert sorted(listes) == sorted(TOOL_NATURE)


@pytest.mark.asyncio
async def test_le_contrat_ne_declare_aucun_engageant_sans_garde(deux_utilisateurs) -> None:
    """`unguarded_engaging_tools()` doit rester vide — et la page le dire."""
    from app.agent.tool_nature import unguarded_engaging_tools
    from app.routers.transparency import visible_contract

    out = await visible_contract(current_user=_fake_user(deux_utilisateurs[0]))
    assert out["summary"]["unguarded_engaging"] == unguarded_engaging_tools()


@pytest.mark.asyncio
async def test_le_contrat_marque_les_passe_plats_comme_non_dispensables(deux_utilisateurs) -> None:
    """Un `*_raw_api_call` ne peut pas etre dispense, meme d'un clic."""
    from app.routers.transparency import visible_contract

    out = await visible_contract(current_user=_fake_user(deux_utilisateurs[0]))
    par_nom = {i["name"]: i for f in out["families"] for i in f["items"]}
    assert par_nom["gmail_raw_api_call"]["waivable"] is False
    assert par_nom["gmail_raw_api_call"]["approval"] == "always"
    assert par_nom["gmail_list_emails"]["waivable"] is True


@pytest.mark.asyncio
async def test_le_regime_affiche_est_celui_que_la_passerelle_appliquerait(
    deux_utilisateurs,
) -> None:
    """Outil par outil : ce que la page AFFICHE == ce que la passerelle DECIDE.

    ⚠️ 02/09/2026, second tour. La page derivait « accord systematique » de
    `tool_nature.ALREADY_GUARDED` (l'union LOCKED_HITL_TOOLS ∪
    ALWAYS_CRITICAL_TOOLS) et de l'effet ENGAGEANT de la table. Or
    `tool_gateway._decide_hitl` ne consulte ni l'une ni l'autre : depuis que
    `trust_substrate_enabled` vaut True par defaut, sa decision de base est
    `manifest_requires_hitl`. Douze outils etaient annonces « la garde les
    retient quoi qu'il arrive » alors que leur confirmation dependait des
    arguments.

    Le test ne compare pas des listes, il EXERCE la decision : pour chaque
    outil, deux descriptions — une anodine, une portant un mot-cle critique —
    et le regime affiche doit correspondre au couple de reponses. Sans quoi
    les deux redivergeront.
    """
    from app.routers.transparency import visible_contract
    from app.services.capability_manifest import manifest_requires_hitl
    from app.services.security_filter import SecurityFilter

    sf = SecurityFilter()
    out = await visible_contract(current_user=_fake_user(deux_utilisateurs[0]))

    ecarts: list[tuple[str, str, str]] = []
    for famille in out["families"]:
        for outil in famille["items"]:
            nom = outil["name"]
            # La passerelle compose exactement cette chaine (cf.
            # `_decide_hitl`) avant de la donner a `is_critical`.
            anodin = f'Outil: {nom} | Arguments: {{"q": "bonjour"}}'
            critique = f'Outil: {nom} | Arguments: {{"q": "supprimer"}}'
            sans_risque = manifest_requires_hitl(nom, anodin, sf.is_critical)
            avec_risque = manifest_requires_hitl(nom, critique, sf.is_critical)
            if sans_risque and avec_risque:
                attendu = "always"
            elif not avec_risque:
                attendu = "never"
            else:
                attendu = "risk_based"
            if outil["approval"] != attendu:
                ecarts.append((nom, outil["approval"], attendu))

    assert not ecarts, (
        f"{len(ecarts)} outils affichent un regime que la passerelle "
        f"n'appliquerait pas : {ecarts[:5]}"
    )


@pytest.mark.asyncio
async def test_le_contrat_nomme_les_dispenses_que_la_passerelle_execute(
    deux_utilisateurs,
) -> None:
    """« Accord systematique » n'est jamais absolu : deux dispenses sont codees.

    L'auto-approbation des mails adresses a soi-meme coupe la garde de trois
    outils d'envoi, et les outils MCP auto-gardes posent `needs_hitl = False`
    sans condition — `mcp_connect` compris, alors qu'il est dans
    LOCKED_HITL_TOOLS. Une page qui affiche « la garde les retient quoi qu'il
    arrive » sans les nommer promet une protection que l'utilisateur n'a pas.
    """
    from app.routers.transparency import visible_contract
    from app.services.tool_gateway import (
        _MCP_SELF_GATING_TOOLS,
        _SELF_MAIL_TOOLS,
    )

    out = await visible_contract(current_user=_fake_user(deux_utilisateurs[0]))
    annonces = {w["tool"]: w for w in out["instance_waivers"]}

    # Tout ce que la passerelle contourne est annonce, et rien d'autre.
    assert set(annonces) == set(_MCP_SELF_GATING_TOOLS) | set(_SELF_MAIL_TOOLS)
    # Une dispense conditionnelle (le destinataire, c'est moi) et une
    # inconditionnelle ne se lisent pas pareil : la page doit les distinguer.
    for nom in _SELF_MAIL_TOOLS:
        assert annonces[nom]["conditional"] is True
    for nom in _MCP_SELF_GATING_TOOLS:
        assert annonces[nom]["conditional"] is False

    par_nom = {i["name"]: i for f in out["families"] for i in f["items"]}
    for nom in set(annonces) & set(par_nom):
        assert par_nom[nom]["waiver_reason"], f"{nom} : dispense muette sur la carte"


@pytest.mark.asyncio
async def test_le_compte_des_annulables_vient_avec_l_etat_du_journal(
    deux_utilisateurs, monkeypatch,
) -> None:
    """Drapeau eteint, rien n'est enregistre — donc rien n'est annulable.

    Le compte des annulables mesure ce qui est OUTILLE (une compensation
    executable existe). Il ne mesure pas ce qui est RECUPERABLE : quand
    `reversible_journal_enabled` est OFF — sa valeur par defaut — la
    passerelle n'appelle jamais `record_reversible`. Annoncer le compte seul,
    c'est promettre un « Annuler » qui n'a rien a annuler.
    """
    from app.config import get_settings
    from app.routers.transparency import visible_contract

    reglages = get_settings()
    monkeypatch.setattr(reglages, "reversible_journal_enabled", False)
    eteint = await visible_contract(current_user=_fake_user(deux_utilisateurs[0]))
    assert eteint["summary"]["revertible"] > 0
    assert eteint["summary"]["revertible_journal_enabled"] is False

    monkeypatch.setattr(reglages, "reversible_journal_enabled", True)
    allume = await visible_contract(current_user=_fake_user(deux_utilisateurs[0]))
    assert allume["summary"]["revertible_journal_enabled"] is True


@pytest.mark.asyncio
async def test_le_contrat_n_annonce_annulable_que_ce_qui_l_est(deux_utilisateurs) -> None:
    """« Annulable » veut dire qu'une compensation EXECUTABLE existe.

    Le manifeste peut nommer une compensation absente du registre ; l'annonce
    doit suivre le registre, pas le nom.
    """
    from app.routers.transparency import visible_contract
    from app.services.compensation_registry import get_compensation

    out = await visible_contract(current_user=_fake_user(deux_utilisateurs[0]))
    annulables = [
        i for f in out["families"] for i in f["items"] if i["revertible"]
    ]
    assert annulables, "aucun outil annulable — le registre en porte trois"
    for item in annulables:
        assert get_compensation(item["compensation"]) is not None


@pytest.mark.asyncio
async def test_la_dispense_d_un_utilisateur_ne_deborde_pas_sur_l_autre(deux_utilisateurs) -> None:
    from app.database import async_session
    from app.models.hitl_preference import HitlPreference
    from app.routers.transparency import visible_contract

    moi, autre = deux_utilisateurs
    async with async_session() as db:
        db.add(HitlPreference(
            user_id=moi, tool_name="drive_delete_file", requires_confirmation=False,
        ))
        await db.commit()

    mien = await visible_contract(current_user=_fake_user(moi))
    sien = await visible_contract(current_user=_fake_user(autre))

    def pref(page):
        return {
            i["name"]: i["user_preference"]
            for f in page["families"] for i in f["items"]
        }["drive_delete_file"]

    assert pref(mien) == "waived"
    assert pref(sien) is None
    assert mien["summary"]["waived_by_user"] == 1
    assert sien["summary"]["waived_by_user"] == 0


@pytest.mark.asyncio
async def test_une_dispense_ecrite_sur_un_passe_plat_est_annoncee_neutralisee(
    deux_utilisateurs,
) -> None:
    """Une ligne ecrite avant le 02/09/2026 survit en base mais ne vaut plus.

    La page doit le DIRE : afficher « dispense » sans preciser qu'elle est
    ignoree ferait croire l'utilisateur decouvert alors qu'il est protege.
    """
    from app.database import async_session
    from app.models.hitl_preference import HitlPreference
    from app.routers.transparency import visible_contract

    moi = deux_utilisateurs[0]
    async with async_session() as db:
        db.add(HitlPreference(
            user_id=moi, tool_name="drive_raw_api_call", requires_confirmation=False,
        ))
        await db.commit()

    out = await visible_contract(current_user=_fake_user(moi))
    par_nom = {i["name"]: i for f in out["families"] for i in f["items"]}
    assert par_nom["drive_raw_api_call"]["user_preference"] == "waived"
    assert par_nom["drive_raw_api_call"]["user_preference_effective"] is False
    assert "drive_raw_api_call" in out["summary"]["neutralized_user_waivers"]


@pytest.mark.asyncio
async def test_le_contrat_ne_montre_que_les_mandats_de_l_utilisateur(deux_utilisateurs) -> None:
    from app.database import async_session
    from app.models.mission import Mission
    from app.routers.transparency import visible_contract
    from app.services.mission_spec import MissionMandate, mandate_to_json

    moi, autre = deux_utilisateurs
    mandat = mandate_to_json(MissionMandate(tools_allow=("web_search",)))
    async with async_session() as db:
        for uid, titre in ((moi, "le mien"), (autre, "le sien")):
            db.add(Mission(
                user_id=uid, title=titre, goal="g", status="running",
                mandate_json=mandat, autonomy_state="active",
            ))
        await db.commit()

    out = await visible_contract(current_user=_fake_user(moi))
    assert [m["title"] for m in out["mandates"]] == ["le mien"]
    assert out["mandates"][0]["tools_allow"] == ["web_search"]


@pytest.mark.asyncio
async def test_un_mandat_de_mission_terminee_n_est_plus_annonce_actif(
    deux_utilisateurs,
) -> None:
    """Une mission que l'utilisateur a ARRETEE n'accorde plus rien.

    ⚠️ 02/09/2026. Le filtre excluait « cancelled » — un statut qui n'existe
    dans aucune constante du depot — et n'excluait pas « aborted », celui
    d'une mission tuee par l'utilisateur. La page annoncait donc, sous
    « mandats actifs », un pouvoir revoque. On exerce ici les trois statuts
    terminaux, lus dans la constante.
    """
    from app.database import async_session
    from app.models.mission import MISSION_TERMINAL_STATUSES, Mission
    from app.routers.transparency import visible_contract
    from app.services.mission_spec import MissionMandate, mandate_to_json

    moi = deux_utilisateurs[0]
    mandat = mandate_to_json(MissionMandate(tools_allow=("web_search",)))
    async with async_session() as db:
        for statut in sorted(MISSION_TERMINAL_STATUSES):
            db.add(Mission(
                user_id=moi, title=f"finie_{statut}", goal="g", status=statut,
                mandate_json=mandat, autonomy_state="active",
            ))
        db.add(Mission(
            user_id=moi, title="en_cours", goal="g", status="running",
            mandate_json=mandat, autonomy_state="active",
        ))
        await db.commit()

    out = await visible_contract(current_user=_fake_user(moi))
    assert [m["title"] for m in out["mandates"]] == ["en_cours"]


# ── Le registre de sortie : borne, cloisonne, et sobre ───────────────────


@pytest.mark.asyncio
async def test_le_registre_ne_compte_que_les_lignes_de_l_utilisateur(deux_utilisateurs) -> None:
    from app.routers.transparency import egress_registry

    moi, autre = deux_utilisateurs
    await _log(moi, provider="anthropic", skill="a_moi", channel="web")
    await _log(autre, provider="anthropic", skill="a_lui", channel="telegram")
    await _log(autre, provider="ollama", skill="a_lui", channel="telegram")

    out = await egress_registry(days=7, current_user=_fake_user(moi))
    assert out["totals"]["calls"] == 1
    assert out["totals"]["cloud_calls"] == 1
    assert out["totals"]["local_calls"] == 0
    # Ni la destination, ni l'usage, ni le canal du voisin ne transpirent :
    # chacune des quatre agregations porte sa propre clause `user_id`, et une
    # seule oubliee suffirait a montrer a qui l'autre parle.
    assert [d["provider"] for d in out["destinations"]] == ["anthropic"]
    assert [u["skill"] for u in out["purposes"]] == ["a_moi"]
    assert [c["channel"] for c in out["channels"]] == ["web"]


@pytest.mark.asyncio
async def test_le_registre_borne_la_fenetre(deux_utilisateurs) -> None:
    from app.routers.transparency import egress_registry

    moi = deux_utilisateurs[0]
    await _log(moi, provider="anthropic", jours=0)
    await _log(moi, provider="anthropic", jours=40)

    out = await egress_registry(days=7, current_user=_fake_user(moi))
    assert out["totals"]["calls"] == 1
    assert out["window_days"] == 7
    assert len(out["by_day"]) == 7


@pytest.mark.asyncio
async def test_le_registre_refuse_une_fenetre_hors_bornes(deux_utilisateurs) -> None:
    """Un `days=99999` transformerait la page en agregation de toute l'histoire.

    `usage_logs` ne fait que grossir : la borne est le garde-fou, pas la bonne
    volonte de l'appelant.
    """
    from app.auth.dependencies import get_current_user

    app = _app()
    app.dependency_overrides[get_current_user] = lambda: _fake_user(deux_utilisateurs[0])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t",
    ) as client:
        assert (await client.get("/api/me/transparency/egress?days=99999")).status_code == 422
        assert (await client.get("/api/me/transparency/egress?days=0")).status_code == 422
        ok = await client.get("/api/me/transparency/egress?days=7")
    assert ok.status_code == 200, ok.text
    assert ok.json()["window_days"] == 7


@pytest.mark.asyncio
async def test_le_registre_separe_local_nuage_et_inconnu(deux_utilisateurs) -> None:
    """« Inconnu » est une reponse ; le compter en local serait une invention."""
    from app.routers.transparency import egress_registry

    moi = deux_utilisateurs[0]
    await _log(moi, provider="lm_studio")
    await _log(moi, provider="ollama")
    await _log(moi, provider="anthropic")
    await _log(moi, provider="unknown")
    await _log(moi, provider=None)

    out = await egress_registry(days=7, current_user=_fake_user(moi))
    assert out["totals"]["local_calls"] == 2
    assert out["totals"]["cloud_calls"] == 1
    assert out["totals"]["unknown_calls"] == 2
    kinds = {d["provider"]: d["kind"] for d in out["destinations"]}
    assert kinds["lm_studio"] == "local"
    assert kinds["anthropic"] == "cloud"
    assert kinds["unknown"] == "unknown"


@pytest.mark.asyncio
async def test_le_registre_ventile_par_date(deux_utilisateurs) -> None:
    from app.routers.transparency import egress_registry

    moi = deux_utilisateurs[0]
    await _log(moi, provider="anthropic", jours=0)
    await _log(moi, provider="ollama", jours=2)

    out = await egress_registry(days=7, current_user=_fake_user(moi))
    jours = {d["day"]: d for d in out["by_day"]}
    assert len(jours) == 7
    aujourdhui = (datetime.now(timezone.utc) - timedelta(minutes=1)).date().isoformat()
    avant_hier = (
        datetime.now(timezone.utc) - timedelta(days=2, minutes=1)
    ).date().isoformat()
    assert jours[aujourdhui]["cloud"] == 1
    assert jours[avant_hier]["local"] == 1


@pytest.mark.asyncio
async def test_la_fenetre_lue_commence_au_premier_jour_affiche(deux_utilisateurs) -> None:
    """La fenetre ANNONCEE doit etre celle qui est LUE.

    Une borne glissante (« il y a N fois 24 heures ») ne coincide pas avec les
    N journees affichees : elle attrape la fin de la veille du premier jour
    montre. Ces appels-la se comptaient dans les totaux sans avoir de barre ou
    se poser — le total et la frise se contredisaient, sur une page dont c'est
    justement le contraire qu'on attend.
    """
    from app.routers.transparency import egress_registry

    out = await egress_registry(days=7, current_user=_fake_user(deux_utilisateurs[0]))
    premier = out["by_day"][0]["day"]
    assert out["since"] == f"{premier}T00:00:00+00:00"


@pytest.mark.asyncio
async def test_aucun_appel_compte_n_echappe_a_la_ventilation(deux_utilisateurs) -> None:
    """Ce que le total compte, la frise le montre — sinon l'un des deux ment."""
    from datetime import time as _time

    from app.routers.transparency import egress_registry

    moi = deux_utilisateurs[0]
    premier = datetime.now(timezone.utc).date() - timedelta(days=6)  # jours=7
    veille = premier - timedelta(days=1)

    # Le tout premier instant de la fenetre affichee : il compte.
    await _log(moi, provider="anthropic",
               at=datetime.combine(premier, _time(0, 0, 30), tzinfo=timezone.utc))
    # La toute fin de la veille : hors fenetre, donc hors total.
    await _log(moi, provider="anthropic",
               at=datetime.combine(veille, _time(23, 59, 30), tzinfo=timezone.utc))

    out = await egress_registry(days=7, current_user=_fake_user(moi))
    assert out["totals"]["calls"] == 1
    assert out["by_day"][0]["day"] == premier.isoformat()
    assert out["by_day"][0]["cloud"] == 1
    ventiles = sum(j["local"] + j["cloud"] + j["unknown"] for j in out["by_day"])
    assert ventiles == out["totals"]["calls"]


@pytest.mark.asyncio
async def test_le_registre_dit_les_usages_et_les_canaux(deux_utilisateurs) -> None:
    from app.routers.transparency import egress_registry

    moi = deux_utilisateurs[0]
    await _log(moi, provider="anthropic", skill="gmail_list_emails", channel="telegram")
    await _log(moi, provider="anthropic", skill="gmail_list_emails", channel="web")

    out = await egress_registry(days=7, current_user=_fake_user(moi))
    usages = {u["skill"]: u["calls"] for u in out["purposes"]}
    assert usages["gmail_list_emails"] == 2
    canaux = {c["channel"]: c["calls"] for c in out["channels"]}
    assert canaux == {"telegram": 1, "web": 1}


@pytest.mark.asyncio
async def test_le_registre_ne_pretend_pas_avoir_mesure_les_masquages(deux_utilisateurs) -> None:
    """LE point qui rend cette page honnete.

    `usage_logs` ne sait pas dire si une valeur a ete REMPLACEE pendant ce
    tour. La page annonce donc la regle appliquee et les categories couvertes,
    et declare la mesure absente. Un « 12 donnees masquees » invente ici
    detruirait la seule chose que cette page apporte.
    """
    from app.routers.transparency import egress_registry

    out = await egress_registry(days=7, current_user=_fake_user(deux_utilisateurs[0]))
    masquage = out["masking"]
    assert masquage["substitutions_measured"] is False
    assert "EMAIL" in masquage["regex_categories"]
    assert isinstance(masquage["ner_enabled"], bool)


@pytest.mark.asyncio
async def test_le_registre_nomme_les_chemins_qui_n_anonymisent_pas(
    deux_utilisateurs,
) -> None:
    """La page ne dit plus « avant TOUT appel de modele » : c'etait faux.

    ⚠️ 02/09/2026. Le champ etait un booleen code en dur a True. Deux chemins
    envoient du texte BRUT : la generation du titre d'une conversation et la
    corvee de consolidation de fin de conversation, qui relit les messages en
    base. Les deux visent le tier MAINTENANCE, souvent local — mais
    « souvent » n'est pas « toujours », et c'est exactement la question a
    laquelle cette page repond.

    Le test refuse l'affirmation absolue et exige que les exceptions soient
    NOMMEES : une page qui tait ce qu'elle ne couvre pas rassure a tort.
    """
    from app.routers.transparency import egress_registry

    out = await egress_registry(days=7, current_user=_fake_user(deux_utilisateurs[0]))
    masquage = out["masking"]

    assert "applied_before_every_model_call" not in masquage
    assert masquage["applied_on"], "aucun chemin verifie annonce"
    # 03/09/2026 : les deux trous sont fermes, la liste est vide — mais un
    # chemin qu'on y remettrait devra etre NOMME, jamais tu.
    assert isinstance(masquage["not_applied_on"], list)
    for trou in masquage["not_applied_on"]:
        assert trou["path"] and trou["what"]
    couverts = {c["path"] for c in masquage["applied_on"]}
    assert "titre de conversation" in couverts
    assert "resume de fin de conversation" in couverts


@pytest.mark.asyncio
async def test_le_registre_echantillonne_la_composition_de_ce_qui_sort(
    deux_utilisateurs,
) -> None:
    """La ventilation du contexte n'existe que sur les tours qui l'ont ecrite.

    On dit donc sur COMBIEN d'appels elle porte — sinon un pourcentage tire de
    trois tours passerait pour la verite de la fenetre.
    """
    from app.routers.transparency import egress_registry

    moi = deux_utilisateurs[0]
    await _log(moi, provider="anthropic",
               breakdown='{"system_prompt":100,"conversation":300,"total":400,"pct":3}')
    await _log(moi, provider="anthropic")  # sans ventilation

    out = await egress_registry(days=7, current_user=_fake_user(moi))
    compo = out["composition"]
    assert compo["sampled_calls"] == 1
    parts = {c["key"]: c["tokens"] for c in compo["categories"]}
    assert parts == {"system_prompt": 100, "conversation": 300}


@pytest.mark.asyncio
async def test_les_tours_locaux_ne_mangent_pas_l_echantillon_du_nuage(
    deux_utilisateurs, monkeypatch,
) -> None:
    """Le plafond doit porter sur ce qu'on compte, pas sur ce qu'on jette.

    ⚠️ 02/09/2026. Le plafond etait applique AVANT le filtre « nuage » : sur
    une instance qui tourne surtout en local, les N tours les plus recents
    pouvaient etre locaux, `sampled_calls` tombait a zero et la page imprimait
    une phrase categorique alors que des appels nuage ventiles existaient dans
    la fenetre.

    Le plafond est rabaisse a 2 pour exercer le cas sans ecrire 200 lignes.
    """
    import app.routers.transparency as tr
    from app.routers.transparency import egress_registry

    monkeypatch.setattr(tr, "_COMPOSITION_SAMPLE", 2)

    moi = deux_utilisateurs[0]
    maintenant = datetime.now(timezone.utc) - timedelta(minutes=1)
    ventilation = '{"system_prompt":50,"conversation":150,"total":200}'
    # Les deux tours les plus RECENTS sont locaux : avant le correctif ils
    # remplissaient l'echantillon a eux seuls.
    await _log(moi, provider="lm_studio", breakdown=ventilation, at=maintenant)
    await _log(moi, provider="ollama", breakdown=ventilation,
               at=maintenant - timedelta(minutes=1))
    await _log(moi, provider="anthropic", breakdown=ventilation,
               at=maintenant - timedelta(minutes=2))
    # Descendre le critere dans la requete ne doit pas requalifier l'INCONNU
    # en sorti : `NOT IN` ne rend jamais vrai face a NULL, exactement comme
    # `_kind` range un fournisseur non renseigne en « unknown ».
    await _log(moi, provider=None, breakdown=ventilation,
               at=maintenant - timedelta(minutes=3))

    compo = (await egress_registry(days=7, current_user=_fake_user(moi)))["composition"]
    assert compo["sampled_calls"] == 1
    assert {c["key"] for c in compo["categories"]} == {"system_prompt", "conversation"}


@pytest.mark.asyncio
async def test_le_registre_dit_le_plafond_de_la_liste_des_usages(
    deux_utilisateurs,
) -> None:
    """Un plafond tu se lit comme un inventaire complet.

    La section voisine annonce la taille de son echantillon
    (`composition.sample_cap`) ; la liste des usages etait tronquee a douze
    sans le dire — « voila tout ce pour quoi elle appelle un modele ».
    """
    from app.routers.transparency import _TOP_PURPOSES, egress_registry

    moi = deux_utilisateurs[0]
    for i in range(_TOP_PURPOSES + 3):
        await _log(moi, provider="anthropic", skill=f"usage_{i:02d}")

    out = await egress_registry(days=7, current_user=_fake_user(moi))
    assert out["purposes_cap"] == _TOP_PURPOSES
    assert len(out["purposes"]) == _TOP_PURPOSES
