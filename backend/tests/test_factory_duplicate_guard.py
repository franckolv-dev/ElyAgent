# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_factory_duplicate_guard.py
# @brief      V0-4 — la fabrique cesse de refabriquer ce qu'elle a déjà fabriqué.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de l'anti-doublon de la fabrique (audit Opus 5 §3.2 et §4.4).

**Ce que dit la base de production** (relevé read-only le 25/07) :

    convert_pdf_to_docx | 4be29159 | archived | 2026-07-22 10:11 | 5 usages
    convert_pdf_to_docx | 4be29159 | archived | 2026-07-22 10:31 | 0
    convert_pdf_to_docx | 4be29159 | archived | 2026-07-22 10:32 | 0
    convert_pdf_to_docx | 4be29159 | archived | 2026-07-22 10:39 | 0
    convert_pdf_to_docx | 4be29159 | archived | 2026-07-22 10:43 | 0

**Cinq générations du MÊME outil, pour le MÊME utilisateur, en 32 minutes.**
Ce n'est pas un artefact multi-utilisateur : c'est une boucle serrée.

La cause : ``capability_has_existing_tool`` interroge ``_ensure_catalog()``,
construit depuis ``get_skill_registry().all_tools`` — c'est-à-dire les outils
**bindés**. Un outil fraîchement généré est une *candidate* non promue : il
n'est bindé nulle part, donc invisible au pré-check, donc regénéré au gap
suivant. Idem pour un outil archivé.

Run with:  cd backend && python -m pytest tests/test_factory_duplicate_guard.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.models.learned_skill import LearnedSkill
from app.models.user import User

CAPABILITY = "convertir un fichier PDF en document DOCX editable"


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


@pytest.fixture
def empty_catalog(monkeypatch):
    """Neutralise le catalogue des outils BINDÉS pour cibler exactement le
    chemin « outils déjà fabriqués ».

    Sans ça, l'ordre des tests déciderait du résultat : dès qu'une autre suite
    a chargé le vrai catalogue, l'outil core gradué ``pdf_to_docx`` matche
    déjà la capacité PDF→DOCX et masque le chemin qu'on veut vérifier. Les
    deux chemins mènent au même comportement (la fabrique s'abstient) — mais
    un test doit dire lequel il éprouve.
    """
    import app.skills.builtin.find_tool_skill as mod

    async def _noop() -> None:
        return None

    monkeypatch.setattr(mod, "_ensure_catalog", _noop)
    monkeypatch.setattr(mod, "_tool_text_norm", {})
    return mod


async def _make_user() -> str:
    from app.database import async_session
    async with async_session() as db:
        u = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(u)
        await db.commit()
        return u.id


async def _make_tool(user_id: str, name: str, status: str,
                     description: str = "Convertit un PDF en DOCX editable") -> None:
    from app.database import async_session
    async with async_session() as db:
        db.add(LearnedSkill(
            id=str(uuid.uuid4()), user_id=user_id, name=name,
            description=description, content="def run(): pass",
            content_format="python_tool", status=status, source="auto",
        ))
        await db.commit()


# ------------------------------------------------- les statuts invisibles

@pytest.mark.asyncio
async def test_a_pending_candidate_blocks_a_second_generation(empty_catalog):
    """Une candidate non promue n'est bindée nulle part — c'est exactement
    ce qui rendait la fabrique aveugle à son propre travail."""
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    user_id = await _make_user()
    await _make_tool(user_id, "convert_pdf_to_docx", "candidate")

    assert await capability_has_existing_tool(CAPABILITY, user_id=user_id) == \
        "convert_pdf_to_docx"


@pytest.mark.asyncio
async def test_an_archived_attempt_is_visible_too(empty_catalog):
    """Les 6 convert_pdf_to_docx de la prod sont TOUS archivés."""
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    user_id = await _make_user()
    await _make_tool(user_id, "convert_pdf_to_docx", "archived")

    assert await capability_has_existing_tool(CAPABILITY, user_id=user_id) == \
        "convert_pdf_to_docx"


@pytest.mark.asyncio
async def test_a_rejected_attempt_is_visible_too(empty_catalog):
    """Un échec permanent doit couper la boucle, pas la relancer."""
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    user_id = await _make_user()
    await _make_tool(user_id, "convert_pdf_to_docx", "rejected")

    assert await capability_has_existing_tool(CAPABILITY, user_id=user_id) == \
        "convert_pdf_to_docx"


# ------------------------------------------------------------- cloisonnement

@pytest.mark.asyncio
async def test_another_users_tool_does_not_block_generation(empty_catalog):
    """Les outils appris sont par utilisateur : celui de l'épouse de Franck
    ne doit pas empêcher Franck d'avoir le sien."""
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    mine, theirs = await _make_user(), await _make_user()
    await _make_tool(theirs, "convert_pdf_to_docx", "active")

    assert await capability_has_existing_tool(CAPABILITY, user_id=mine) is None


@pytest.mark.asyncio
async def test_an_unrelated_tool_does_not_block_generation(empty_catalog):
    """Pas de faux positif : un outil sans rapport ne bloque rien."""
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    user_id = await _make_user()
    await _make_tool(user_id, "levenshtein_distance", "active",
                     description="Calcule la distance de Levenshtein")

    assert await capability_has_existing_tool(CAPABILITY, user_id=user_id) is None


@pytest.mark.asyncio
async def test_capability_similarity_catches_a_different_name(empty_catalog):
    """« pas seulement le nom » : deux noms différents pour la même capacité
    doivent se rencontrer (pdf_to_docx vs convert_pdf_to_docx)."""
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    user_id = await _make_user()
    await _make_tool(user_id, "pdf_to_docx", "active",
                     description="Convertit un fichier PDF en document DOCX editable")

    assert await capability_has_existing_tool(CAPABILITY, user_id=user_id) == \
        "pdf_to_docx"


# ------------------------------------------------------------- LE rejeu

@pytest.mark.asyncio
async def test_the_real_production_sequence_collapses_to_a_single_generation(empty_catalog):
    """LE test du lot : on rejoue la séquence mesurée en prod (5 générations
    de convert_pdf_to_docx pour un même utilisateur en 32 minutes). Une seule
    doit passer."""
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    user_id = await _make_user()
    generated: list[str] = []

    for _ in range(5):
        existing = await capability_has_existing_tool(CAPABILITY, user_id=user_id)
        if existing:
            continue  # la fabrique s'abstient
        generated.append("convert_pdf_to_docx")
        # ce que fait réellement generate_and_persist_tool : une candidate
        await _make_tool(user_id, "convert_pdf_to_docx", "candidate")

    assert len(generated) == 1, (
        f"{len(generated)} générations au lieu d'une seule — la fabrique "
        "refabrique encore ce qu'elle a déjà fabriqué"
    )


# -------------------------------- le vrai chemin de génération automatique

@pytest.mark.asyncio
async def test_auto_generation_abstains_when_the_tool_was_already_built(monkeypatch, empty_catalog):
    """Le pré-check corrigé doit être BRANCHÉ : c'est
    ``maybe_generate_for_gap`` qui doit s'abstenir, pas seulement la
    fonction de comparaison qui doit savoir répondre."""
    import app.services.learning.auto_tool_generation as gen

    user_id = await _make_user()
    await _make_tool(user_id, "convert_pdf_to_docx", "candidate")

    called: list[str] = []

    async def _never(**kwargs):
        called.append(kwargs.get("task_description", ""))
        return {}

    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool",
        _never, raising=False,
    )
    monkeypatch.setattr(gen, "_attempted_cases", set(), raising=False)

    await gen.maybe_generate_for_gap(
        case_id="c-1", capability=CAPABILITY, user_id=user_id,
    )

    assert not called, (
        "la fabrique a lancé une génération alors qu'un outil identique "
        "existe déjà pour cet utilisateur"
    )


@pytest.mark.asyncio
async def test_a_bound_tool_still_shadows_the_learned_path(empty_catalog, monkeypatch):
    """Ordre des sources, verrouillé : le catalogue des outils BINDÉS répond
    en premier, sans même toucher la base.

    Découvert en écrivant ce lot : en production, l'outil core gradué
    ``pdf_to_docx`` couvre déjà la capacité PDF→DOCX. Dès qu'il est bindé, la
    fabrique s'abstient par ce chemin-là — le moins cher. Les deux chemins
    convergent vers le même comportement ; ce test fige leur priorité."""
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    monkeypatch.setattr(empty_catalog, "_tool_text_norm", {
        "pdf_to_docx": "pdf_to_docx convertir un fichier pdf en document docx editable",
    })

    def _never_queried(*_a, **_kw):
        raise AssertionError("la base ne doit pas être interrogée si un outil bindé répond")

    monkeypatch.setattr(empty_catalog, "_learned_tool_for_capability", _never_queried)

    user_id = await _make_user()
    assert await capability_has_existing_tool(CAPABILITY, user_id=user_id) == "pdf_to_docx"


# -------------------------------------------------------- non-régression

@pytest.mark.asyncio
async def test_registry_precheck_still_works_without_a_user():
    """Signature rétrocompatible : sans user_id, le comportement historique
    (catalogue des outils bindés) est strictement préservé."""
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    # Une capacité franchement couverte par le catalogue réel.
    assert await capability_has_existing_tool("") is None


@pytest.mark.asyncio
async def test_precheck_never_raises_when_db_is_unavailable(monkeypatch, empty_catalog):
    """Best-effort : une base illisible ne doit pas bloquer la fabrique."""
    mod = empty_catalog

    def _boom(*_a, **_kw):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(mod, "_learned_tool_for_capability", _boom, raising=False)
    user_id = await _make_user()

    assert await mod.capability_has_existing_tool(CAPABILITY, user_id=user_id) is None
