# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_un_compte_sous_accord.py
# @brief      Lot 3 (07/09/2026) : une mission peut créer un compte pour
#             l'utilisateur, sous son accord, sans qu'un mot de passe
#             transite jamais par le modèle.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""L'objectif de Franck : « plutôt que me dire "il faut créer un compte sur
XYZ", qu'elle prenne l'initiative, quitte à me demander l'autorisation ».

Ce que le dépôt avait : un coffre chiffré (AES-GCM, Argon2id), résolu par la
passerelle sur toute valeur `vault://label` — et rien d'autre. Aucun outil
pour que le modèle sache quels secrets existent, aucun pour en créer un, et
`browser_fill` renvoyait « rempli avec la valeur : 'S3cr3t' » : le secret
résolu repartait EN CLAIR au modèle et dans les traces.

Trois pièces :
- la passerelle remasque, dans le résultat d'un outil, tout secret qu'elle a
  résolu (il redevient `vault://label`) ;
- `vault_list_labels` et `vault_generate_secret` : le modèle voit des
  étiquettes, jamais des valeurs, et fabrique un mot de passe fort qu'il ne
  lit pas ;
- un playbook amorcé « créer un compte pour l'utilisateur » : accord par
  `ask_user`, secret généré, formulaire rempli par référence, confirmation
  lue dans Gmail, CAPTCHA remonté par capture + question.

Run with:  cd backend && python -m pytest tests/test_un_compte_sous_accord.py -v
"""
from __future__ import annotations

import string
import uuid

import pytest
import pytest_asyncio

from app.database import init_db

_MDP = "motdepasse-de-test-1"


@pytest_asyncio.fixture
async def coffre_ouvert():
    """Un utilisateur avec son coffre créé et déverrouillé."""
    await init_db()
    from app.database import async_session
    from app.models.user import User
    from app.services.vault_service import get_vault_service
    from tests._user_cleanup import purge_user

    uid = f"test_vault_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    vault = get_vault_service()
    assert await vault.unlock_vault(uid, _MDP)
    yield uid, vault
    await vault.lock_vault(uid)
    await purge_user(uid)


def _ctx(user_id: str):
    from app.services.conversation_filters import get_filter
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import GatewayContext

    conv = f"conv-vault-{uuid.uuid4()}"
    return GatewayContext(
        user_id=user_id, conversation_id=conv,
        pii_filter=get_filter(conv), criticality_filter=SecurityFilter(),
        hitl=None, memory=None,
    )


class _OutilQuiEchoLaValeur:
    """Le contrat de `browser_fill` : il renvoie ce qu'il a tapé."""

    name = "browser_fill"

    async def ainvoke(self, args):
        return f"Champ {args['selector']!r} rempli avec la valeur : {args['value']!r}"


# ── 1. La passerelle remasque ce qu'elle a résolu ───────────────────────────


@pytest.mark.asyncio
async def test_un_secret_resolu_ne_repart_jamais_en_clair_au_modele(coffre_ouvert):
    uid, vault = coffre_ouvert
    await vault.store_secret(uid, "site-x", "S3cr3t-Valeur!", "compte de test")
    from app.services.tool_gateway import execute_tool_call

    msg = await execute_tool_call(
        _ctx(uid),
        {"name": "browser_fill", "args": {"selector": "#password", "value": "vault://site-x"},
         "id": "t-vault"},
        {"browser_fill": _OutilQuiEchoLaValeur()},
    )

    contenu = msg["content"] if isinstance(msg, dict) else msg.content
    assert "S3cr3t-Valeur!" not in contenu, "le secret résolu est reparti en clair"
    assert "vault://site-x" in contenu


@pytest.mark.asyncio
async def test_un_coffre_verrouille_refuse_sans_rien_reveler(coffre_ouvert):
    uid, vault = coffre_ouvert
    await vault.store_secret(uid, "site-x", "S3cr3t-Valeur!")
    await vault.lock_vault(uid)
    from app.services.tool_gateway import execute_tool_call

    msg = await execute_tool_call(
        _ctx(uid),
        {"name": "browser_fill", "args": {"selector": "#p", "value": "vault://site-x"}, "id": "t2"},
        {"browser_fill": _OutilQuiEchoLaValeur()},
    )
    contenu = msg["content"] if isinstance(msg, dict) else msg.content
    assert "verrouillé" in contenu.lower()
    assert "S3cr3t" not in contenu
    assert await vault.unlock_vault(uid, _MDP)


# ── 2. Les outils du coffre pour le modèle ──────────────────────────────────


@pytest.mark.asyncio
async def test_le_modele_voit_les_etiquettes_jamais_les_valeurs(coffre_ouvert):
    uid, vault = coffre_ouvert
    await vault.store_secret(uid, "mon-compte-xyz", "S3cr3t-Valeur!", "compte XYZ, identifiant = franck")
    from app.agent.tools.vault_tools import vault_list_labels

    texte = await vault_list_labels.ainvoke({"user_id": uid})

    assert "mon-compte-xyz" in texte
    assert "identifiant = franck" in texte
    assert "S3cr3t" not in texte
    assert "vault://mon-compte-xyz" in texte, "le mode d'emploi de la référence doit y être"


@pytest.mark.asyncio
async def test_generer_un_secret_rend_une_reference_et_jamais_la_valeur(coffre_ouvert):
    uid, vault = coffre_ouvert
    from app.agent.tools.vault_tools import vault_generate_secret

    texte = await vault_generate_secret.ainvoke({"label": "compte-xyz", "hint": "site XYZ", "user_id": uid})

    assert "vault://compte-xyz" in texte
    valeur = await vault.get_secret(uid, "compte-xyz")
    assert len(valeur) >= 20
    assert any(c.islower() for c in valeur) and any(c.isupper() for c in valeur)
    assert any(c.isdigit() for c in valeur) and any(c in string.punctuation for c in valeur)
    assert valeur not in texte, "la valeur ne doit jamais être rendue au modèle"
    etiquettes = await vault.list_secrets(uid)
    assert any(e["label"] == "compte-xyz" and "XYZ" in (e.get("hint") or "") for e in etiquettes)


@pytest.mark.asyncio
async def test_generer_ne_remplace_pas_un_secret_existant(coffre_ouvert):
    uid, vault = coffre_ouvert
    await vault.store_secret(uid, "compte-xyz", "ancien")
    from app.agent.tools.vault_tools import vault_generate_secret

    texte = await vault_generate_secret.ainvoke({"label": "compte-xyz", "user_id": uid})

    assert "existe déjà" in texte.lower()
    assert await vault.get_secret(uid, "compte-xyz") == "ancien"


@pytest.mark.asyncio
async def test_les_outils_du_coffre_disent_de_le_deverrouiller(coffre_ouvert):
    uid, vault = coffre_ouvert
    await vault.lock_vault(uid)
    from app.agent.tools.vault_tools import vault_generate_secret, vault_list_labels

    a = await vault_list_labels.ainvoke({"user_id": uid})
    b = await vault_generate_secret.ainvoke({"label": "x", "user_id": uid})
    assert "verrouillé" in a.lower() and "verrouillé" in b.lower()
    assert "ask_user" in b, "en mission, la voie de sortie est de demander à l'utilisateur"
    assert await vault.unlock_vault(uid, _MDP)


def test_une_etiquette_invalide_est_refusee_sans_toucher_au_coffre():
    from app.agent.tools.vault_tools import etiquette_valide

    assert etiquette_valide("compte-xyz.fr_2")
    assert not etiquette_valide("compte xyz")
    assert not etiquette_valide("")
    assert not etiquette_valide("a" * 121)


def test_les_outils_du_coffre_sont_classes_et_recoivent_l_utilisateur():
    from app.agent.tool_nature import TOOL_NATURE, requires_approval
    from app.agent.tool_sets import USER_ID_TOOLS
    from app.services.security_filter import NEVER_AUTONOMOUS_TOOLS

    assert {"vault_list_labels", "vault_generate_secret"} <= USER_ID_TOOLS
    assert TOOL_NATURE["vault_list_labels"].effect == "LECTURE"
    assert TOOL_NATURE["vault_generate_secret"].effect == "ECRITURE"
    assert requires_approval("vault_generate_secret") is False
    # Une mission de nuit doit pouvoir créer son mot de passe : pas au plancher.
    assert "vault_generate_secret" not in NEVER_AUTONOMOUS_TOOLS


# ── 3. La procédure ─────────────────────────────────────────────────────────


def test_un_playbook_amorce_dit_comment_creer_un_compte_sous_accord():
    from app.services.learning.seed_playbooks import SEED_PLAYBOOKS

    seeds = {s["name"]: s for s in SEED_PLAYBOOKS}
    assert "creer-un-compte-pour-l-utilisateur" in seeds
    corps = seeds["creer-un-compte-pour-l-utilisateur"]["body"]
    for attendu in ("ask_user", "vault_list_labels", "vault_generate_secret",
                    "vault://", "browser_fill", "gmail", "browser_screenshot", "MEDIA:"):
        assert attendu in corps, f"le playbook ne parle pas de {attendu}"
    assert "en clair" in corps.lower()
    assert {"compte", "inscription"} <= set(seeds["creer-un-compte-pour-l-utilisateur"]["tags"])


def test_la_consigne_de_mission_sait_creer_un_compte():
    from app.agent.missions.chat_loop import _consigne

    texte = _consigne("Trouve le prix du produit X sur le site Y.", "")
    assert "vault_generate_secret" in texte
    assert "en clair" in texte.lower()


def test_browser_fill_explique_la_reference_au_coffre():
    from app.skills.builtin.browser_skill import browser_fill

    assert "vault://" in (browser_fill.description or "")
