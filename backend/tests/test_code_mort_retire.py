# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_code_mort_retire.py
# @brief      Ménage 02/09/2026 — deux morceaux inertes qui coûtaient quand
#             même : une collection Qdrant créée à vide à chaque boot, et un
#             outil de démonstration bindé dans le registre de production.
# @license    Elastic License 2.0
# =============================================================================
"""Ce qui ne sert à rien coûte quand même quelque chose.

**1 — La collection Qdrant `procedures`.** Le Sprint 2.5 avait prévu un index
sémantique sur la table SQL `procedures`. Le `ProceduralStore` est resté un
stub sans voie d'écriture, retiré depuis (voir `test_inert_code_removed.py`),
et la moisson n'a jamais été livrée. La lecture, elle, a été rebranchée le
02/08 — mais sur le REGISTRE D'OUTILS, pas sur Qdrant : `_recall_procedural`
appelle `rank_tools_for_capability`, et `memory/inspection.py` annonce noir sur
blanc « Pas de magasin ». Il ne restait donc qu'un geste : `init_collections`
créait la collection à chaque démarrage, personne n'y écrivait, personne n'y
lisait.

**2 — Le tool `fibonacci`.** Vitrine du pipeline de graduation (Sprint 4d),
mergée le 11/06. Le registre l'auto-découvre par `walk_packages` : il comptait
donc dans les 200 outils du catalogue de production, avec sa ligne dans
`tool_nature.py`. `enabled_by_default=False` ne l'empêchait de rien avant le
24/08 — c'est justement lui qui a servi de preuve à l'incident #342.

⚠️ Le paquet `agent/tools/graduated/` RESTE, lui, et ce pin le tient : ce n'est
pas un dossier d'exemples, c'est la cible d'écriture de la graduation
(`graduation_codegen.GRADUATED_PKG_DIR`). Le vider ne le rend pas inutile.

Run with:  cd backend && python -m pytest tests/test_code_mort_retire.py -v
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


# ─────────────────────────────────────────────────────────────────────
# 1 — La collection `procedures`
# ─────────────────────────────────────────────────────────────────────


class _FauxClientQdrant:
    """Le strict nécessaire pour observer ce que `init_collections` crée."""

    def __init__(self, existantes: tuple[str, ...] = ()) -> None:
        self.existantes = existantes
        self.creees: list[str] = []
        self.indexees: list[str] = []

    def get_collections(self):
        return SimpleNamespace(
            collections=[SimpleNamespace(name=n) for n in self.existantes]
        )

    def create_collection(self, name, vectors_config=None):
        self.creees.append(name)

    def create_payload_index(self, name, field_name=None, field_schema=None):
        self.indexees.append(name)


# Les quatre collections qui restent vivantes après le retrait de `procedures`.
# Écrites en toutes lettres : c'est l'ANCRE des assertions ci-dessous, elles ne
# doivent dépendre d'aucune valeur produite par le code sous test.
_COLLECTIONS_VIVANTES = {
    "memories",
    "user_profile",
    "security_constraints",
    "interactions",
}


async def _collections_creees_au_demarrage(
    existantes: tuple[str, ...] = (),
) -> _FauxClientQdrant:
    from app.services.memory_manager import MemoryManager

    faux = _FauxClientQdrant(existantes)
    mgr = object.__new__(MemoryManager)  # pas de Qdrant réel, pas de fastembed
    mgr._infra = SimpleNamespace(client=faux)
    await mgr.init_collections()
    return faux


@pytest.mark.asyncio
async def test_le_demarrage_ne_cree_plus_la_collection_procedures():
    """LE pin. Une collection sans lecteur ni écrivain n'a pas à naître."""
    faux = await _collections_creees_au_demarrage()
    assert "procedures" not in faux.creees


@pytest.mark.asyncio
async def test_le_demarrage_cree_toujours_les_quatre_collections_vivantes():
    """Le garde-fou de la suppression : on retire une collection, pas quatre."""
    faux = await _collections_creees_au_demarrage()
    assert set(faux.creees) == _COLLECTIONS_VIVANTES


@pytest.mark.asyncio
async def test_lindex_user_id_est_toujours_pose_sur_chaque_collection():
    """L'index payload est ce qui empêche Qdrant de scanner à N users
    (revue 2026-06-10 §4). Il vit dans la MÊME boucle que la création :
    en retirer un nom ne doit pas en emporter la pose.

    ⚠️ Relecture 02/09/2026 : l'assertion comparait `indexees` à `creees`, deux
    listes remplies par la MÊME boucle. `init_collections` enveloppe tout dans
    un `except Exception` qui avale : un client qui lève dès `get_collections`
    donnait deux listes vides et un test vert sur une init morte. On ancre donc
    sur les noms attendus."""
    faux = await _collections_creees_au_demarrage()
    assert set(faux.indexees) == _COLLECTIONS_VIVANTES


@pytest.mark.asyncio
async def test_lindex_user_id_est_repose_sur_une_collection_deja_existante():
    """Le second boot ne crée plus rien mais doit quand même passer l'index :
    c'est ce qui rattrape les collections nées avant la revue 2026-06-10."""
    faux = await _collections_creees_au_demarrage(
        existantes=tuple(_COLLECTIONS_VIVANTES)
    )
    assert faux.creees == []
    assert set(faux.indexees) == _COLLECTIONS_VIVANTES


def test_la_constante_de_collection_procedures_a_disparu():
    """Laissée seule, elle ferait croire à un index qui n'existe nulle part."""
    constants = importlib.import_module("app.services.memory._constants")
    assert not hasattr(constants, "COLLECTION_PROCEDURES")


@pytest.mark.asyncio
async def test_la_memoire_procedurale_reste_consultable_sans_collection():
    """⚠️ Ce qu'on ne casse PAS. `procedural` est redevenu lisible le 02/08 —
    servi par le registre d'outils. Retirer la collection Qdrant ne doit pas
    reprendre cette lecture-là."""
    from app.services.memory.recall_service import MemoryRecallService
    from app.services.memory.types import MemoryType
    from app.skills.builtin import register_all

    register_all()  # la source de `procedural`, c'est le registre lui-même
    svc = object.__new__(MemoryRecallService)
    hits = await svc._recall_procedural("chercher sur le web", "u-1", 3)
    assert hits, "le catalogue d'outils doit toujours répondre"
    assert all(h.type is MemoryType.PROCEDURAL for h in hits)


# ─────────────────────────────────────────────────────────────────────
# 2 — Le tool de démonstration `fibonacci`
# ─────────────────────────────────────────────────────────────────────


def test_le_module_du_tool_fibonacci_a_disparu():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.agent.tools.graduated.fibonacci_tool")


def test_fibonacci_nest_plus_un_outil_enregistre():
    """L'auto-découverte le prenait : il pesait dans le catalogue de prod."""
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    assert "fibonacci" not in {t.name for t in get_skill_registry().all_tools}


def test_le_paquet_des_tools_gradues_reste_importable():
    """⚠️ Le dossier reste, vide. C'est la CIBLE D'ÉCRITURE de la graduation :
    `graduation_codegen` y dépose `<nom>_tool.py` et l'importe sous
    `app.agent.tools.graduated.<nom>_tool`. Sans paquet, la prochaine
    graduation produit une PR qui ne s'importe pas."""
    from app.services.learning.graduation_codegen import graduated_tool_path

    importlib.import_module("app.agent.tools.graduated")
    assert graduated_tool_path("truc") == (
        "backend/app/agent/tools/graduated/truc_tool.py"
    )
