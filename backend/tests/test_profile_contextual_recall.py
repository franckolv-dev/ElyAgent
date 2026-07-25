# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_profile_contextual_recall.py
# @brief      C2-b — les faits qu'Ely a stockés redeviennent atteignables quand
#             la question les rend pertinents.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du rappel contextuel du profil (chantier C2, « rappel à la demande »).

**Le trou, vérifié dans le code.** ``_PROFILE_NOISY_KEYS`` porte ce
commentaire : *« They remain in the DB and can still be retrieved via the
semantic RAG path when relevant. »* **Aucun code ne tient cette promesse.**
La table `user_profiles` n'est lue qu'à deux endroits — l'injection plafonnée
à 800 caractères et un rapport admin. Le magasin sémantique
(`semantic_user_store.py`) interroge des collections Qdrant, et sa propre
docstring dit que la réconciliation avec SQL « happens in V2 (Sprint 2.8) » —
elle n'a jamais été faite.

Une clé classée bruyante est donc **inatteignable, point**. Ce n'est pas un
aiguillage vers une autre voie : c'est une suppression déguisée. Et ça touche
`upcoming_events` (les rendez-vous), `gmail_preferences`, `shopping_routine`…

**Pourquoi un bloc séparé, et pas un profil plus gros.** Le snapshot mémoire
est **gelé par conversation** (`frozen_memory.get_or_build` : *« returns the
same cached string regardless of any memory updates »*). Y mettre des faits
choisis selon la question ne servirait que la PREMIÈRE question du fil et
tromperait sur toutes les suivantes.

Le rappel contextuel vit donc dans la **zone volatile** du prompt, là où la
date est déjà placée — le code explique pourquoi : *« Date en DERNIER — c'est
la partie la plus volatile […] on limite l'invalidation du cache aux ~30
derniers tokens. »* Un bloc court, recalculé à chaque tour, après le contenu
stable : le snapshot gelé reste gelé, le cache de prompt reste efficace.

Run with:  cd backend && python -m pytest tests/test_profile_contextual_recall.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.models.user import User
from app.models.user_memory import UserProfile


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


async def _user_with_profile(entries: list[tuple[str, str]]) -> str:
    from app.database import async_session
    async with async_session() as db:
        u = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(u)
        await db.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for key, value in entries:
            db.add(UserProfile(
                user_id=u.id, key=key, value=value,
                confidence=1.0, source_count=1,
                last_seen=now - timedelta(days=5),
            ))
        await db.commit()
        return u.id


# --------------------------------------------- ce que la promesse doit tenir

@pytest.mark.asyncio
async def test_a_noisy_key_becomes_reachable_when_the_question_calls_for_it():
    """LE test du lot. `upcoming_events` est classé bruyant, donc absent du
    profil permanent — et jusqu'ici de partout. Quand l'utilisateur demande
    ses rendez-vous, le fait doit revenir."""
    from app.services.memory_service import get_query_relevant_profile

    uid = await _user_with_profile([
        ("upcoming_events", "RDV médical Dr Rassinoux le 19/05 à 9h"),
        ("mobile_provider", "Free Mobile"),
    ])

    block = await get_query_relevant_profile(uid, "j'ai un rendez-vous médical bientôt ?")

    assert "Rassinoux" in block, "les rendez-vous restent inatteignables"


@pytest.mark.asyncio
async def test_an_operational_fact_surfaces_on_its_topic():
    """`email_facture_process` (rang 110 sur 238) n'atteint jamais le profil
    permanent. Il doit revenir quand on parle de factures."""
    from app.services.memory_service import get_query_relevant_profile

    uid = await _user_with_profile([
        ("email_facture_process", "Analyse mails, pièces jointes vers Drive 'Factures'"),
        ("hardware_setup", "Mac Studio M1, MacBook Air"),
    ])

    block = await get_query_relevant_profile(uid, "où vont mes factures déjà ?")

    assert "Factures" in block
    assert "MacBook" not in block, "un fait hors sujet ne doit pas remplir le bloc"


@pytest.mark.asyncio
async def test_nothing_is_returned_when_nothing_matches():
    """Pas de remplissage : un bloc vide vaut mieux qu'un bloc au hasard, le
    prompt système a un plafond de 15 000 caractères."""
    from app.services.memory_service import get_query_relevant_profile

    uid = await _user_with_profile([("mobile_provider", "Free Mobile")])

    assert await get_query_relevant_profile(uid, "explique-moi la mécanique quantique") == ""


@pytest.mark.asyncio
async def test_an_empty_query_returns_nothing():
    """Sans question, pas de rappel contextuel — le profil permanent suffit."""
    from app.services.memory_service import get_query_relevant_profile

    uid = await _user_with_profile([("upcoming_events", "RDV le 19/05")])

    assert await get_query_relevant_profile(uid, "") == ""


# ------------------------------------------------- pas de doublon avec le permanent

@pytest.mark.asyncio
async def test_facts_already_in_the_permanent_profile_are_not_repeated():
    """Le nom de l'utilisateur est déjà injecté en permanence : le redire
    dans le bloc contextuel gaspillerait le budget."""
    from app.services.memory_service import get_query_relevant_profile

    uid = await _user_with_profile([
        ("user_name", "Franck Ollivier"),
        ("email_facture_process", "Pièces jointes vers Drive 'Factures'"),
    ])

    block = await get_query_relevant_profile(uid, "Franck, où vont mes factures ?")

    assert "Franck Ollivier" not in block
    assert "Factures" in block


# ---------------------------------------------------- le budget est tenu

@pytest.mark.asyncio
async def test_the_block_stays_small():
    """La zone volatile doit le rester : ce bloc est recalculé à chaque tour
    et invalide d'autant le cache de prompt."""
    from app.services.memory_service import get_query_relevant_profile

    uid = await _user_with_profile([
        (f"facture_{i}", f"circuit de factures numéro {i} " * 12) for i in range(40)
    ])

    block = await get_query_relevant_profile(uid, "factures")

    assert len(block) <= 500, f"bloc contextuel à {len(block)} caractères"


@pytest.mark.asyncio
async def test_it_never_raises():
    from app.services.memory_service import get_query_relevant_profile

    assert await get_query_relevant_profile("", "factures") == ""
    assert await get_query_relevant_profile("utilisateur-inconnu", "factures") == ""


# ------------------------------------ le snapshot gelé n'est PAS touché

def test_the_frozen_snapshot_is_not_made_query_dependent():
    """Garde-fou d'architecture. Le snapshot mémoire est gelé par
    conversation ; y injecter des faits choisis selon la question ne servirait
    que le PREMIER tour et tromperait sur les suivants. Le rappel contextuel
    doit vivre ailleurs."""
    from pathlib import Path

    src = Path("app/agent/builders/memory_snapshot.py").read_text(encoding="utf-8")

    assert "get_query_relevant_profile" not in src, (
        "le rappel contextuel a été mis dans le snapshot GELÉ — il ne "
        "servirait que la première question de chaque conversation"
    )


def test_the_recall_is_wired_in_the_volatile_zone():
    """Il doit être calculé par tour et assemblé AVEC la date — jamais dans
    le segment mis en cache. La date reste le tout dernier élément : c'est
    le plus volatile, et le code le place là exprès pour ne rendre caduques
    que les derniers tokens du prompt."""
    from pathlib import Path

    src = Path("app/agent/nodes.py").read_text(encoding="utf-8")

    assert "get_query_relevant_profile" in src
    # Le bloc rejoint le segment volatile, pas le prompt cacheable.
    assert "_volatile_segment" in src
    assert "_recall_block" in src
    assert src.count("cacheable_system + _date_segment") == 0, (
        "un assemblage utilise encore la date seule : le rappel contextuel "
        "n y arriverait pas"
    )
    # Et il est bien calculé AVANT d etre assemble.
    assert src.index("_recall_block = await") < src.index("_volatile_segment =") + 1
