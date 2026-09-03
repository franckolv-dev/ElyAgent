# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_v1_surface_alignment.py
# @brief      V1 temps 1 — les canaux et la voix passent sur le runtime unique,
#             sans rien perdre au passage.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins de l'alignement des surfaces (vague 1, temps 1 — non destructif).

**Pourquoi.** Le banc A/B (`docs_internes/v2_mesure_architectures.md`) a tranché :
le mono-agent est plus rapide (+64 % en tier B, +9,6 s au p50 en tier A local)
et choisit mieux ses outils (85 % contre 78 %, 100 % contre 62 % en local).
Reste à faire arriver ce runtime sur les 5 surfaces qui ne l'ont pas.

**Ce que les canaux GAGNENT** en basculant : les outils qu'Ely s'est créés
(absents de 5 surfaces sur 7 aujourd'hui), le bloc `<learned_skills>`, le
vecteur d'état utilisateur, les préférences, le cache mémoire par conversation
et la rotation LLM « sticky ».

**Ce qu'ils PERDRAIENT sans précaution** — et c'est le cœur de ce lot : le
**vocabulaire personnel** (onboarding) n'est injecté que par
`sub_agents/factory.py:478` et `missions/nodes.py`. Le chemin mono ne l'a
jamais eu. Basculer les canaux sans le porter d'abord serait une régression
silencieuse pour les utilisateurs qui ont fait l'onboarding.

Temps 1 est **non destructif** : `supervisor.py` et `sub_agents/factory.py`
restent en place. Leur suppression est le temps 2.

Run with:  cd backend && python -m pytest tests/test_v1_surface_alignment.py -v
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from app.models.conversation import Conversation
from app.models.user import User


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


async def _make_conversation() -> tuple[str, str]:
    from app.database import async_session
    async with async_session() as db:
        u = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(u)
        await db.flush()
        c = Conversation(user_id=u.id, title="[Telegram] test")
        db.add(c)
        await db.commit()
        return u.id, str(c.id)


# ------------------------------------------- résolution partagée du profil

@pytest.mark.asyncio
async def test_profile_is_auto_detected_and_persisted_on_the_first_turn():
    from app.agent.toolset_profiles import resolve_conversation_profile
    from app.database import async_session

    _uid, conv_id = await _make_conversation()

    profile = await resolve_conversation_profile(conv_id, "est-ce que j'ai des mails ?")

    assert profile, "aucun profil résolu — le routeur ne sera pas court-circuité"
    async with async_session() as db:
        assert (await db.get(Conversation, conv_id)).toolset_profile == profile


@pytest.mark.asyncio
async def test_profile_is_stable_across_turns():
    """Le catalogue d'outils doit rester stable pour le modèle : le deuxième
    tour réutilise le profil du premier, il ne le re-détecte pas."""
    from app.agent.toolset_profiles import resolve_conversation_profile
    from app.database import async_session
    from app.models.conversation import Conversation as C

    _uid, conv_id = await _make_conversation()
    async with async_session() as db:
        conv = await db.get(C, conv_id)
        conv.toolset_profile = "un_profil_fige"
        await db.commit()

    assert await resolve_conversation_profile(conv_id, "tout autre chose") == "un_profil_fige"


@pytest.mark.asyncio
async def test_profile_resolution_never_raises():
    """Une conversation inconnue ou une base indisponible ne doit pas casser
    un tour : on retombe sur le chemin historique (chaîne vide)."""
    from app.agent.toolset_profiles import resolve_conversation_profile

    assert await resolve_conversation_profile("conversation-inexistante", "x") == ""
    assert await resolve_conversation_profile("", "x") == ""


# ------------------------ LE garde-fou : ne rien perdre en basculant

@pytest.mark.asyncio
async def test_personal_vocabulary_reaches_the_mono_agent_prompt():
    """Régression à empêcher : le vocabulaire d'onboarding n'existait que
    dans `sub_agents/factory.py`. Sans ce portage, tout utilisateur passant
    des canaux au runtime unique perdrait son vocabulaire personnel."""
    from app.agent.builders.system_prompt import build_personal_vocabulary_block

    assert callable(build_personal_vocabulary_block)


def test_the_mono_path_injects_the_vocabulary():
    """Pin source : le chemin mono doit appeler l'injection, sinon le portage
    existe mais ne sert à rien."""
    src = Path("app/agent/nodes.py").read_text(encoding="utf-8")

    assert "build_personal_vocabulary_block" in src, (
        "le chemin mono n'injecte pas le vocabulaire personnel — "
        "basculer les canaux le leur ferait perdre"
    )


@pytest.mark.asyncio
async def test_vocabulary_block_is_empty_for_a_user_without_onboarding():
    """Pas de bruit dans le prompt (plafond de 15 000 caractères) pour les
    utilisateurs qui n'ont pas fait l'onboarding."""
    from app.agent.builders.system_prompt import build_personal_vocabulary_block

    assert await build_personal_vocabulary_block("utilisateur-inconnu") == ""


@pytest.mark.asyncio
async def test_vocabulary_injection_never_raises():
    from app.agent.builders.system_prompt import build_personal_vocabulary_block

    assert await build_personal_vocabulary_block("") == ""


# --------------------------------- les 5 surfaces passent bien le profil

@pytest.mark.parametrize("surface", [
    "app/channels/telegram_bot.py",
    "app/routers/voice.py",
])
def test_every_surface_passes_the_toolset_profile(surface):
    """Sans ce champ, le routeur s'exécute et la demande part vers un
    sous-agent — c'est exactement ce que la mesure a invalidé."""
    src = Path(surface).read_text(encoding="utf-8")

    assert "resolve_conversation_profile" in src, f"{surface} ne résout aucun profil"
    assert "toolset_profile" in src, f"{surface} ne transmet pas le profil au graphe"


@pytest.mark.parametrize("surface", [
    "app/channels/telegram_bot.py",
])
def test_the_profile_is_resolved_before_the_agent_is_invoked(surface):
    src = Path(surface).read_text(encoding="utf-8")

    assert src.index("resolve_conversation_profile") < src.index("agent.ainvoke"), (
        f"{surface} résout le profil APRÈS avoir invoqué l'agent"
    )


# ------------------------------ le routeur est bien court-circuité

def test_there_is_no_router_left_to_bypass():
    """Au temps 1, ce test vérifiait que le `toolset_profile` court-circuitait
    bien le routeur. Au temps 2, il n'y a plus de routeur du tout : le
    contrat est devenu structurel."""
    from app.agent.graph import build_agent_graph

    assert "router" not in set(build_agent_graph().get_graph().nodes)


# -------------------------------- temps 1 est NON DESTRUCTIF

def test_the_supervisor_is_gone_since_temps_2():
    """Ce test assertait l'inverse au temps 1 : le superviseur devait RESTER,
    parce que l'alignement des surfaces devait être réversible. Le temps 2
    (26/07) l'a supprimé — voir `test_v1_runtime_unified.py`."""
    assert not Path("app/agent/supervisor.py").exists()
    assert not Path("app/agent/sub_agents").exists()
