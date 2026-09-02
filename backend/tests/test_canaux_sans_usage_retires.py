# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_canaux_sans_usage_retires.py
# @brief      Audit 02/09/2026 — WhatsApp, Slack, Discord et l'Arena quittent
#             le chemin critique : zéro appel mesuré en cinq mois.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de retrait des surfaces sans usage.

**La mesure.** Sur cinq mois de production, les appels de modèle se répartissent
ainsi par canal : fond 7 277, web 1 994, missions 1 494, tier S 207, ntfy 154,
planifié 151, Telegram 3 — et **WhatsApp 0, Slack 0, Discord 0**. L'Arena, elle,
totalise 6 matchs. Ce n'est pas un usage faible, c'est l'absence d'usage : trois
ponts entrants et un comparateur de modèles que personne n'a jamais employés,
mais qui pesaient sur le démarrage, la configuration, le catalogue d'outils et
l'image Docker.

**Le cas WhatsApp est doublement tranché.** Le `.env` de production ne porte
aucune des quatre variables `WHATSAPP_*` : l'outil sortant `whatsapp_send`
répondait donc « WhatsApp non configuré » à chaque appel, indépendamment du
compte de messages entrants. Il part avec les deux ponts.

**Ce que chaque pin garantit** :

1. les modules ne s'importent plus — le code est parti sous ``archive/``, pas
   seulement débranché ;
2. ``app.main`` ne les câble plus, vérifié en **important** l'application : un
   débranchement à moitié fait lèverait ici ;
3. les réglages morts ont quitté ``Settings`` — un champ qui survit à son
   lecteur redevient un piège de configuration ;
4. le catalogue d'outils n'annonce plus ``whatsapp_send`` : un outil injoignable
   annoncé au modèle est pire qu'un outil absent, il fait mentir la réponse ;
5. les tables de l'Arena quittent ``Base.metadata``, sinon ``create_all`` les
   recréerait au prochain démarrage sur base fraîche ;
6. les trois dépendances quittent ``pyproject.toml`` — c'est le seul pin qui
   rend le retrait visible dans l'image Docker.

⚠️ Les tables ``arena_match`` et ``arena_elo`` restent dans les bases DÉJÀ
déployées : supprimer des données utilisateur demande une migration décidée,
qui n'est pas dans ce lot.

Run with:  cd backend && python -m pytest tests/test_canaux_sans_usage_retires.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import tomllib
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. Le code est parti
# ---------------------------------------------------------------------------

_MODULES_RETIRES = [
    "app.channels.whatsapp",
    "app.channels.whatsapp_web",
    "app.channels.slack_bot",
    "app.channels.discord_bot",
    "app.routers.whatsapp_webhook",
    "app.routers.whatsapp_web",
    "app.agent.tools.whatsapp_tool",
    "app.skills.builtin.whatsapp_skill",
    "app.routers.arena",
    "app.services.arena_service",
    "app.models.arena",
]


@pytest.mark.parametrize("module", _MODULES_RETIRES)
def test_le_module_archive_ne_simporte_plus(module: str) -> None:
    """Un module archivé doit être introuvable, pas seulement inutilisé."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


@pytest.mark.parametrize("module", _MODULES_RETIRES)
def test_le_fichier_archive_a_quitte_le_paquet(module: str) -> None:
    """Le fichier a bougé sur le disque, il n'est pas seulement vidé."""
    relpath = module.replace(".", "/") + ".py"
    assert not (_BACKEND / relpath).exists(), f"{relpath} est encore là"


# ---------------------------------------------------------------------------
# 2. L'application ne les câble plus — vérifié par IMPORT, pas par grep
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prefixe", [
    "/api/whatsapp",
    "/api/channels/slack",
    "/api/channels/discord",
    "/api/arena",
])
def test_aucune_route_exposee_pour_un_canal_retire(prefixe: str) -> None:
    """Importer l'app réelle : un router resté câblé ferait lever l'import."""
    from app.main import app

    exposees = [
        r.path for r in app.routes
        if getattr(r, "path", "").startswith(prefixe)
    ]
    assert exposees == [], f"routes encore exposées : {exposees}"


def test_le_paquet_des_canaux_ne_garde_que_ceux_qui_servent() -> None:
    """Telegram sert (3 appels mesurés), les trois autres non."""
    canaux = {p.stem for p in (_BACKEND / "app" / "channels").glob("*.py")}
    assert "telegram_bot" in canaux, "Telegram sert : il ne doit PAS partir"
    assert canaux & {"slack_bot", "discord_bot", "whatsapp", "whatsapp_web"} == set()


# ---------------------------------------------------------------------------
# 3. Les réglages morts ont quitté la configuration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("champ", [
    "whatsapp_phone_number_id",
    "whatsapp_access_token",
    "whatsapp_webhook_verify_token",
    "whatsapp_app_secret",
    "slack_bot_token",
    "slack_app_token",
    "discord_bot_token",
])
def test_le_reglage_mort_a_quitte_les_settings(champ: str) -> None:
    """Un réglage sans lecteur reste un piège : il se remplit sans effet."""
    from app.config import Settings

    assert champ not in Settings.model_fields, f"{champ} survit à son lecteur"


def test_telegram_et_ntfy_gardent_leur_reglage() -> None:
    """Contre-épreuve : le ménage ne doit pas emporter ce qui sert."""
    from app.config import Settings

    assert "telegram_bot_token" in Settings.model_fields
    assert "ntfy_url" in Settings.model_fields


# ---------------------------------------------------------------------------
# 4. Le catalogue d'outils n'annonce plus un outil injoignable
# ---------------------------------------------------------------------------

def test_le_catalogue_nannonce_plus_denvoi_whatsapp() -> None:
    """`whatsapp_send` n'a jamais pu partir : aucun credential Meta en prod.

    ⚠️ 02/09/2026 — relecture adverse. Ce test passait AUSSI sans le retrait :
    `import app.skills.builtin` n'enregistre rien (le paquet expose
    `register_all()`, qu'il faut appeler), les deux assertions négatives
    portaient donc sur un registre VIDE et étaient vraies par construction.
    D'où la contre-épreuve : un catalogue peuplé AVANT d'affirmer une absence.
    """
    from app.skills.builtin import register_all
    from app.skills.registry import get_skill_registry

    register_all()
    registre = get_skill_registry()
    noms = registre.all_tool_names()
    assert len(noms) > 150, (
        f"catalogue quasi vide ({len(noms)} outils) : l'absence ne prouve rien"
    )
    assert {"whatsapp_send", "whatsapp_send_template"} & noms == set()
    assert "whatsapp" not in {s.name for s in registre.list_skills()}


# ---------------------------------------------------------------------------
# 5. Les tables de l'Arena ne seront pas recréées sur une base fraîche
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("table", ["arena_match", "arena_elo"])
def test_la_table_arena_quitte_les_metadonnees(table: str) -> None:
    """`create_all` ne doit plus la recréer au démarrage d'une base neuve."""
    from app.database import Base
    import app.models  # noqa: F401 — enregistre toutes les tables

    assert table not in Base.metadata.tables


# ---------------------------------------------------------------------------
# 6. Les dépendances quittent l'image
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("paquet", ["neonize", "slack-bolt", "discord.py"])
def test_la_dependance_du_canal_retire_nest_plus_declaree(paquet: str) -> None:
    """Le seul pin qui rende le retrait visible dans l'image Docker."""
    deps = tomllib.loads(
        (_BACKEND / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["dependencies"]
    declares = {d.split(">=")[0].split("[")[0].strip() for d in deps}
    assert paquet.split("[")[0] not in declares


# ---------------------------------------------------------------------------
# 7. Une préférence restée sur un canal retiré ne rend pas l'utilisateur muet
# ---------------------------------------------------------------------------
#
# ⚠️ 02/09/2026 — relecture adverse du lot. Le lot avait ÉCRIT que la
# préférence orpheline « retombe sur all ». Elle ne retombait sur rien :
# `request_validation` lisait la colonne BRUTE sans la confronter à la liste
# blanche. Un compte resté sur « discord » sortait avec fan-out=0 — seul le
# WebSocket prévenait. Sur un chemin sans navigateur (mission, tâche
# planifiée), personne ne prévenait, et la demande expirait en auto-refus.


@asynccontextmanager
async def _utilisateur_avec_canal(canal: str | None) -> AsyncIterator[str]:
    """Crée un compte portant cette préférence HITL, le rend, puis le purge.

    ⚠️ 02/09/2026 — la purge n'est pas de la politesse. `request_validation`
    écrit une ligne `hitl_request` par appel (`persist_request`), et sur une
    base de fichier partagée entre tests, un compte laissé derrière fait
    tomber la suite sur une clé étrangère bien plus loin. C'est l'incident
    qui a rougi la CI le 02/09 (voir `tests/_user_cleanup.py`).
    """
    from app.database import async_session, init_db
    from app.models.user import User

    await init_db()
    uid = uuid.uuid4().hex
    async with async_session() as db:
        db.add(User(
            id=uid,
            username=f"u_{uid[:8]}",
            email=f"{uid[:8]}@test.local",
            hashed_password="x",
            hitl_preferred_channel=canal,
        ))
        await db.commit()
    try:
        yield uid
    finally:
        await purge_user(uid)


from tests._user_cleanup import purge_user  # noqa: E402


async def _canaux_notifies(user_id: str) -> list[str]:
    """Joue une demande de validation réelle et rend les canaux touchés."""
    from app.services.hitl_manager import HITLManager

    manager = HITLManager()
    envois: list[str] = []

    async def _frontend(*_a, **_k) -> None:
        envois.append("web")

    async def _telegram(*_a, **_k) -> None:
        envois.append("telegram")

    async def _ntfy(*_a, **_k) -> None:
        envois.append("ntfy")

    async def _fcm(*_a, **_k) -> None:
        envois.append("fcm")

    manager._notify_frontend = _frontend      # type: ignore[method-assign]
    manager._send_telegram = _telegram        # type: ignore[method-assign]
    manager._send_ntfy = _ntfy                # type: ignore[method-assign]
    manager._send_fcm = _fcm                  # type: ignore[method-assign]

    tache = asyncio.create_task(manager.request_validation("Supprimer /data", user_id))
    for _ in range(500):
        await asyncio.sleep(0.01)
        if manager._pending:
            break
    action_id = next(iter(manager._pending))
    await manager.resolve(action_id, "allow")
    await tache
    await asyncio.sleep(0)  # laisse partir la tâche FCM lancée par `spawn`
    return envois


@pytest.mark.asyncio
async def test_une_preference_sur_un_canal_retire_previent_quand_meme() -> None:
    """« discord » n'existe plus : la demande doit partir sur ce qui livre."""
    async with _utilisateur_avec_canal("discord") as user_id:
        envois = await _canaux_notifies(user_id)

    assert "telegram" in envois, "un canal orphelin rend l'utilisateur muet"
    assert "ntfy" in envois, "un canal orphelin rend l'utilisateur muet"


@pytest.mark.asyncio
async def test_une_preference_vivante_reste_honoree() -> None:
    """Contre-épreuve : normaliser l'orphelin ne doit pas tout diffuser."""
    async with _utilisateur_avec_canal("telegram") as user_id:
        envois = await _canaux_notifies(user_id)

    assert "telegram" in envois
    assert "ntfy" not in envois, "la préférence explicite n'est plus honorée"


# ---------------------------------------------------------------------------
# 8. Chaque canal proposé doit avoir un envoyeur
# ---------------------------------------------------------------------------
#
# ⚠️ 02/09/2026 — POURQUOI CE PIN. La normalisation ferme la classe de bug par
# un côté seulement : `normalize_channel` protège d'une valeur EN BASE qui
# n'est plus dans la liste blanche. L'autre sens reste ouvert — les trois
# drapeaux d'envoi de `request_validation` sont un tuple écrit en dur, jamais
# dérivé de `ALLOWED_CHANNELS`. Ajouter demain un canal à la liste blanche
# sans écrire son envoyeur réarme EXACTEMENT le défaut d'origine : la
# préférence se normalise sans broncher, l'éventail tombe à zéro, et sur un
# chemin sans navigateur la demande expire en auto-refus sans que personne
# n'ait été prévenu. Rien ne le verrait — d'où ce pin, qui rend le piège
# bruyant AU MOMENT où la valeur est ajoutée.

from app.services.hitl_channels import ALLOWED_CHANNELS  # noqa: E402

# `web_only` et `all` ne nomment pas un canal : l'un éteint les pushes,
# l'autre les allume tous. Seules les valeurs qui DÉSIGNENT un canal exigent
# un envoyeur.
_CANAUX_NOMMES = sorted(ALLOWED_CHANNELS - {"web_only", "all"})


@pytest.mark.parametrize("canal", _CANAUX_NOMMES)
@pytest.mark.asyncio
async def test_chaque_canal_de_la_liste_blanche_a_un_envoyeur(canal: str) -> None:
    """Une valeur proposée sans chemin d'envoi rend l'utilisateur muet."""
    async with _utilisateur_avec_canal(canal) as user_id:
        envois = await _canaux_notifies(user_id)

    hors_web = [e for e in envois if e != "web"]
    assert hors_web, (
        f"« {canal} » est proposé dans ALLOWED_CHANNELS mais aucun envoi ne "
        f"part hors du navigateur : il faut écrire son envoyeur dans "
        f"HITLManager.request_validation, sinon la préférence est un piège"
    )


# ⚠️ 02/09/2026 — LE MIROIR DU PIN CI-DESSUS. Celui-là ferme le sens « un
# canal proposé sans envoyeur ». L'autre sens restait ouvert : rien
# n'assertait que « all » atteint CHAQUE canal nommé. `_CANAUX_NOMMES` exclut
# « all » par construction, et les deux tests de préférence ne regardent que
# telegram et ntfy — jamais fcm. Ajouter demain un canal AVEC son envoyeur
# mais en l'oubliant dans l'un des trois tuples littéraux de
# `request_validation` laisserait « all » muet sur ce canal, sans test rouge.
# Même racine que le trou de futur d'à côté : les tuples ne sont pas dérivés
# de `ALLOWED_CHANNELS`.
@pytest.mark.asyncio
async def test_all_atteint_chaque_canal_nomme() -> None:
    """« all » veut dire TOUS : un canal oublié dans un tuple rend « all » muet."""
    async with _utilisateur_avec_canal("all") as user_id:
        envois = await _canaux_notifies(user_id)

    hors_web = {e for e in envois if e != "web"}
    attendus = {"telegram", "ntfy", "fcm"}
    assert hors_web == attendus, (
        f"« all » n'arme pas les mêmes canaux que ALLOWED_CHANNELS nomme : "
        f"manquants {sorted(attendus - hors_web)}, en trop "
        f"{sorted(hors_web - attendus)}. Les drapeaux d'envoi de "
        f"HITLManager.request_validation sont des tuples écrits en dur — "
        f"quand la liste blanche bouge, ils doivent bouger avec."
    )
