# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_profile_selection.py
# @brief      C2-a — ce qu'Ely voit de son utilisateur est choisi sur l'utilité,
#             plus sur la répétition.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de la sélection du profil injecté (audit §4.3 / chantier C2).

**Mesuré sur la production le 25/07.** Le profil de Franck compte 238 clés
stockées. Le modèle en voit une douzaine, choisies par
``confidence × source_count`` — soit *combien de fois le fait a été répété*.
Une fréquence, pas une utilité. Conséquence relevée :

| Rang | Clé | Injecté |
|---:|---|:---:|
| 19 | `mobile_provider` (« Free Mobile ») | ✅ |
| 74 | `personal_contacts` (Gert, Gilbert, Stéphane…) | ❌ |
| 92 | `custom_preferences` (ordre d'appel des outils voulu) | ❌ |
| 110 | `email_facture_process` (circuit de factures) | ❌ |
| 150 | `medical_preferences` (motifs de rendez-vous) | ❌ |

Ely connaît l'opérateur mobile de son utilisateur, pas ses proches ni ses
circuits de travail.

⚠️ Vérifié au passage : `upcoming_events` (les rendez-vous) est absent pour
une autre raison — il figure dans `_PROFILE_NOISY_KEYS`, donc il est écarté
**volontairement**. Ce lot ne touche pas à cette liste : c'est un arbitrage
produit, pas un défaut de classement.

**Et le verrou n'est pas le plafond de 800 caractères** : c'est le
``.limit(20)`` de la requête, qui écarte 218 clés *avant* que le moindre
autre critère ne s'applique. Élargir la fenêtre de candidats coûte une
requête un peu plus large et ne change rien au prompt — le plafond de 800
caractères reste, lui, intact : il protège l'attention des petits modèles
locaux (cf. la note PERF du 24/04) et le plafond de 15 000 caractères du
prompt système.

Run with:  cd backend && python -m pytest tests/test_profile_selection.py -v
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


async def _user_with_profile(entries: list[tuple[str, str, float, int, int]]) -> str:
    """entries = (key, value, confidence, source_count, âge en jours)."""
    from app.database import async_session
    async with async_session() as db:
        u = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(u)
        await db.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for key, value, conf, src, age in entries:
            db.add(UserProfile(
                user_id=u.id, key=key, value=value,
                confidence=conf, source_count=src,
                last_seen=now - timedelta(days=age),
            ))
        await db.commit()
        return u.id


# ------------------------------------------- le verrou réel : la fenêtre

@pytest.mark.asyncio
async def test_a_useful_fact_ranked_low_by_frequency_still_reaches_the_model():
    """LE test du lot. Un fait dit une seule fois mais récent et opérationnel
    (un rendez-vous) doit pouvoir passer devant une trivialité répétée
    vingt fois (l'opérateur mobile)."""
    from app.services.memory_service import get_user_context

    entries = [(f"trivia_{i}", f"valeur {i}", 1.0, 40 - i, 200) for i in range(30)]
    entries.append(("personal_contacts", "Gert Wouters, Gilbert Ollivier, Stephane Bonnefoy", 1.0, 1, 0))

    ctx = await get_user_context(await _user_with_profile(entries))

    assert "Gert Wouters" in ctx, (
        "les proches de l utilisateur restent invisibles derrière 30 "
        "trivialités répétées et vieilles de 200 jours"
    )


@pytest.mark.asyncio
async def test_the_candidate_window_is_larger_than_the_old_twenty():
    """238 clés stockées, 20 lues : le `.limit(20)` décidait de tout bien
    avant le budget de caractères."""
    from app.services.memory_service import get_user_context

    entries = [(f"k_{i}", f"v{i}", 1.0, 1, 300) for i in range(25)]
    entries.append(("besoin_recent", "fait récent et utile", 1.0, 1, 0))

    ctx = await get_user_context(await _user_with_profile(entries))

    assert "fait récent et utile" in ctx


# ------------------------------------------------ l'identité reste prioritaire

@pytest.mark.asyncio
async def test_core_identity_always_wins_a_slot():
    """La récence ne doit pas chasser l'identité : sans le nom ni la langue,
    Ely repart de zéro à chaque tour."""
    from app.services.memory_service import get_user_context

    entries = [(f"bruit_{i}", f"événement récent {i}", 1.0, 1, 0) for i in range(40)]
    entries.append(("user_name", "Franck Ollivier", 1.0, 1, 400))
    entries.append(("preferred_language", "français", 1.0, 1, 400))

    ctx = await get_user_context(await _user_with_profile(entries))

    assert "Franck Ollivier" in ctx
    assert "français" in ctx


# --------------------------------------------------------- pas de répétition

@pytest.mark.asyncio
async def test_the_same_value_never_takes_two_slots():
    """Mesuré en prod : `user_email`, `primary_email`, `personal_email` et
    `primary_contact_email` portent la MÊME valeur. Le budget est trop court
    pour dire quatre fois la même chose."""
    from app.services.memory_service import get_user_context

    entries = [
        ("user_email", "franck.olv@gmail.com", 1.0, 30, 10),
        ("primary_email", "franck.olv@gmail.com", 1.0, 29, 10),
        ("personal_email", "franck.olv@gmail.com", 1.0, 28, 10),
        ("primary_contact_email", "franck.olv@gmail.com", 1.0, 27, 10),
        ("location", "Chasseneuil-du-Poitou", 1.0, 26, 10),
    ]

    ctx = await get_user_context(await _user_with_profile(entries))

    assert ctx.count("franck.olv@gmail.com") == 1
    assert "Chasseneuil" in ctx, "la place libérée doit servir à un autre fait"


# ------------------------------------------- le contrat de taille est tenu

@pytest.mark.asyncio
async def test_the_800_character_ceiling_is_still_enforced():
    """Le plafond protège l'attention des petits modèles locaux et le
    plafond de 15 000 caractères du prompt système. Élargir la fenêtre de
    candidats ne doit PAS gonfler le prompt."""
    from app.services.memory_service import get_user_context

    entries = [(f"k_{i}", f"une valeur assez longue pour peser {i}" * 3, 1.0, 5, i)
               for i in range(120)]

    ctx = await get_user_context(await _user_with_profile(entries))

    assert len(ctx) <= 800, f"profil injecté à {len(ctx)} caractères"


@pytest.mark.asyncio
async def test_an_empty_profile_returns_an_empty_string():
    from app.services.memory_service import get_user_context

    assert await get_user_context(await _user_with_profile([])) == ""


@pytest.mark.asyncio
async def test_noisy_keys_are_still_skipped():
    """Le filtre anti-bruit existant ne doit pas être perdu au passage."""
    from app.services.memory_service import _PROFILE_NOISY_KEYS, get_user_context

    noisy = next(iter(_PROFILE_NOISY_KEYS))
    entries = [(noisy, "à ne pas injecter", 1.0, 99, 0), ("user_name", "Franck", 1.0, 1, 0)]

    ctx = await get_user_context(await _user_with_profile(entries))

    assert "à ne pas injecter" not in ctx
    assert "Franck" in ctx


@pytest.mark.asyncio
async def test_the_verbose_mode_is_unchanged():
    """`compact=False` sert au débogage : il doit continuer à tout rendre."""
    from app.services.memory_service import get_user_context

    uid = await _user_with_profile([("a", "un", 1.0, 1, 0), ("b", "deux", 1.0, 1, 0)])

    ctx = await get_user_context(uid, compact=False)

    assert "un" in ctx and "deux" in ctx


@pytest.mark.asyncio
async def test_the_users_own_email_and_timezone_always_reach_the_model():
    """Régression constatée en développant ce lot : la pondération par
    récence faisait sortir `primary_email` du profil injecté. Or Ely en a
    besoin pour s'envoyer un mail à elle-même (`_SELF_MAIL_TOOLS`), et du
    fuseau pour toute planification. Ce sont de l'identité stable, pas des
    faits en compétition."""
    from app.services.memory_service import get_user_context

    entries = [(f"frais_{i}", f"fait très récent {i}", 1.0, 5, 0) for i in range(40)]
    entries.append(("primary_email", "franck.olv@gmail.com", 1.0, 1, 300))
    entries.append(("timezone", "Europe/Paris", 1.0, 1, 300))

    ctx = await get_user_context(await _user_with_profile(entries))

    assert "franck.olv@gmail.com" in ctx
    assert "Europe/Paris" in ctx
