# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_memory_inspection.py
# @brief      Sprint 2.5 §2.5.6 — pins de la surface « Mes mémoires » :
#             cloisonnement par utilisateur, oubli complet, familles non
#             inspectables déclarées, et ordre des routes.
# @license    MIT
# =============================================================================
"""Ce que ces tests empêchent de reperdre.

1. **Le cloisonnement.** `scroll_entries` sans requête liste TOUT : un
   `user_id` vide y serait une fuite inter-comptes bien pire que sur la
   recherche, qui au moins restreint par similarité.
2. **L'oubli à moitié.** Supprimer le vecteur sans la ligne FTS laisse le
   souvenir peser sur le classement plein-texte, invisible mais actif.
3. **La suppression d'autrui.** Le filtre propriétaire vit dans la requête
   Qdrant, pas dans le code appelant.
4. **Les familles muettes.** `procedural` et `error` n'ont pas de surface
   d'audit ; la page doit le DIRE avec la raison, pas les omettre.
5. **L'ordre des routes.** `/api/me/memories/families` doit rester déclarée
   avant `/api/me/memories/{family}`, sinon le curseur la mange.
"""
from __future__ import annotations

import pytest

from app.services.memory import inspection
from app.services.memory.types import MemoryType


class _FakePoint:
    """Un point Qdrant tel que `scroll` le rend (id + payload)."""

    def __init__(self, pid: str, payload: dict) -> None:
        self.id = pid
        self.payload = payload


class _FakeInfra:
    """Infra mémoire factice — garde la signature réelle des deux primitives.

    Volontairement PAS un `**kwargs` : c'est cette signature qui fera
    remarquer un changement de contrat sur `scroll_entries` / `delete_point`.
    """

    def __init__(self, points: list[_FakePoint] | None = None) -> None:
        self.points = points or []
        self.deleted: list[tuple[str, str, str]] = []
        self.refused_empty_user = False

    async def scroll_entries(
        self, collection: str, user_id: str, limit: int, offset: str | None = None
    ) -> tuple[list, str | None]:
        if not user_id:
            self.refused_empty_user = True
            return [], None
        return self.points[:limit], None

    async def delete_point(
        self, collection: str, point_id: str, user_id: str
    ) -> bool:
        if not user_id or not point_id:
            return False
        if not any(p.id == point_id for p in self.points):
            return False
        self.deleted.append((collection, point_id, user_id))
        self.points = [p for p in self.points if p.id != point_id]
        return True


class _FakeFTS:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    async def delete_point(self, qdrant_id: str, user_id: str) -> None:
        self.deleted.append((qdrant_id, user_id))


# ── Parcours ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_entries_maps_payload_to_the_right_text_field(monkeypatch):
    """Chaque famille lit SON champ : les contraintes sont en `rule`, pas
    `content`. Une famille qui lit le mauvais champ affiche des entrées vides
    — la page dirait « rien retenu » sur une mémoire pleine."""
    infra = _FakeInfra([
        _FakePoint("p1", {"rule": "ne jamais supprimer sans demander"}),
    ])
    monkeypatch.setattr(inspection, "get_memory_infra", lambda: infra)

    entries, next_offset = await inspection.list_entries("constraint", "u1")
    assert len(entries) == 1
    assert entries[0].content == "ne jamais supprimer sans demander"
    assert entries[0].type == MemoryType.CONSTRAINT
    assert entries[0].id == "p1"
    assert next_offset is None


@pytest.mark.asyncio
async def test_list_entries_refuses_empty_user_id(monkeypatch):
    """PIN cloisonnement — un parcours sans propriétaire listerait tout le
    monde. La garde vit dans l'infra ; ce test vérifie qu'on la traverse."""
    infra = _FakeInfra([_FakePoint("p1", {"content": "secret d'un autre"})])
    monkeypatch.setattr(inspection, "get_memory_infra", lambda: infra)

    entries, _ = await inspection.list_entries("fact", "")
    assert entries == []
    assert infra.refused_empty_user is True


@pytest.mark.asyncio
async def test_list_entries_unknown_family_raises_keyerror(monkeypatch):
    """Le routeur en fait un 404 nommant les familles valides."""
    monkeypatch.setattr(inspection, "get_memory_infra", lambda: _FakeInfra())
    with pytest.raises(KeyError):
        await inspection.list_entries("spatial", "u1")


@pytest.mark.asyncio
async def test_list_entries_survives_a_missing_collection(monkeypatch):
    """Une collection jamais écrite ne doit pas faire un 500 : la page
    affiche « rien pour l'instant », ce qui est la vérité."""
    class _Boom(_FakeInfra):
        async def scroll_entries(
            self, collection: str, user_id: str, limit: int,
            offset: str | None = None,
        ) -> tuple[list, str | None]:
            raise RuntimeError("collection `interactions` doesn't exist")

    monkeypatch.setattr(inspection, "get_memory_infra", lambda: _Boom())
    entries, next_offset = await inspection.list_entries("episodic", "u1")
    assert entries == [] and next_offset is None


# ── Oubli ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forget_removes_the_vector_and_the_fts_row(monkeypatch):
    """PIN anti-oubli-à-moitié. Sans la ligne FTS, `_search_hybrid` continue
    de booster un identifiant que Qdrant ne connaît plus : le souvenir
    « oublié » pèse encore sur le classement, sans jamais s'afficher."""
    infra = _FakeInfra([_FakePoint("p1", {"content": "un fait"})])
    fts = _FakeFTS()
    monkeypatch.setattr(inspection, "get_memory_infra", lambda: infra)
    monkeypatch.setattr("app.services.fts_store.get_fts_store", lambda: fts)

    assert await inspection.forget_entry("fact", "p1", "u1") is True
    assert infra.deleted == [("memories", "p1", "u1")]
    assert fts.deleted == [("p1", "u1")]


@pytest.mark.asyncio
async def test_forget_returns_false_on_unknown_id(monkeypatch):
    """Le routeur en fait un 404 — indistinguable de « pas à toi », exprès :
    séparer les deux donnerait un oracle d'existence sur la mémoire d'autrui."""
    infra = _FakeInfra([_FakePoint("p1", {"content": "un fait"})])
    monkeypatch.setattr(inspection, "get_memory_infra", lambda: infra)

    assert await inspection.forget_entry("fact", "p-inconnu", "u1") is False
    assert infra.deleted == []


@pytest.mark.asyncio
async def test_forget_reports_success_even_if_fts_cleanup_fails(monkeypatch):
    """Le vecteur est parti : l'entrée ne s'affiche plus et n'est plus
    rappelée. Rendre False ferait afficher « échec » sur une suppression qui
    a bien eu lieu — l'utilisateur recliquerait dans le vide."""
    infra = _FakeInfra([_FakePoint("p1", {"content": "un fait"})])

    class _BrokenFTS:
        async def delete_point(self, qdrant_id: str, user_id: str) -> None:
            raise RuntimeError("sqlite locked")

    monkeypatch.setattr(inspection, "get_memory_infra", lambda: infra)
    monkeypatch.setattr("app.services.fts_store.get_fts_store", lambda: _BrokenFTS())

    assert await inspection.forget_entry("fact", "p1", "u1") is True


# ── Familles ──────────────────────────────────────────────────────────


def test_uninspectable_families_are_declared_with_a_reason():
    """`procedural` et `error` n'ont pas de surface d'audit. La page les
    affiche AVEC la raison : les masquer ferait croire à une mémoire à quatre
    familles, les montrer nus ferait croire à une panne."""
    assert set(inspection.UNINSPECTABLE) == {"procedural", "error"}
    assert all(len(r) > 30 for r in inspection.UNINSPECTABLE.values())
    # Aucun recouvrement : une famille est inspectable OU expliquée, jamais
    # les deux, jamais ni l'une ni l'autre.
    assert not set(inspection.inspectable_families()) & set(inspection.UNINSPECTABLE)


def test_every_readable_memory_type_has_an_inspection_surface():
    """Un type que le modèle peut LIRE doit pouvoir être AUDITÉ.

    Sinon Ely se souvient de quelque chose que son propriétaire ne peut ni
    voir ni oublier — l'inverse du principe « le user possède son agent ».
    Ajouter un type lisible sans surface d'audit casse ici.
    """
    from app.services.memory.recall_service import _UNREADABLE_TYPES

    readable = {
        t for t in MemoryType
        if t not in _UNREADABLE_TYPES and t != MemoryType.AUTO
    }
    audited = {t for _, _, t in inspection._INSPECTABLE.values()}
    # PROCEDURAL est lisible sans être auditable, et c'est justifié : il n'a
    # pas de magasin, il RELIT le registre d'outils. Rien à oublier.
    assert readable - audited == {MemoryType.PROCEDURAL}


# ── Routeur ───────────────────────────────────────────────────────────


def test_families_route_is_declared_before_the_family_placeholder():
    """PIN d'ordre. FastAPI résout dans l'ordre de déclaration : si
    `/{family}` passait devant, `GET /api/me/memories/families` serait routé
    vers le parcours d'une famille nommée « families » → 404 permanent sur la
    page, alors que les trois routes existent."""
    from app.routers.memory import router

    paths = [r.path for r in router.routes]
    assert paths.index("/api/me/memories/families") < paths.index(
        "/api/me/memories/{family}"
    )
