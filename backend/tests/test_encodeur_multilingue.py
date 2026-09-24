# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_encodeur_multilingue.py
# @brief      La mémoire et l'annuaire d'outils sont lus par un encodeur qui
#             comprend le français, et l'index existant est ré-encodé.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mesuré le 24/09/2026 sur 78 vrais appels de ``find_tool`` en production.

L'encodeur de la mémoire était ``all-MiniLM-L6-v2``, un modèle ANGLAIS. Sur
« obtenir les prévisions météo pour demain à Nantes », il rapprochait
``session_todo`` (0,40) bien avant ``weather_get`` (0,14) ; la même phrase en
anglais sortait ``weather_get`` premier. Le repli sémantique de ``find_tool``
plaçait le bon outil en tête 4 fois sur 78. Le même encodeur indexe les
souvenirs, écrits en français.

Avec ``paraphrase-multilingual-MiniLM-L12-v2`` (même dimension, 384) : 25 fois
sur 78 en tête, 38 dans les cinq premiers, 11 ms par requête — mieux que le
sélecteur par modèle local (22/78) qui coûte 2,3 s.

Changer d'encodeur rend illisibles les vecteurs déjà en base : ils ont été
calculés dans un autre espace. D'où le script de ré-encodage, qui relit chaque
point, ré-encode son texte et le réécrit sous le même identifiant.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

from app.services.memory._constants import EMBEDDING_MODEL, VECTOR_DIM

_BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _charger_script():
    chemin = _BACKEND / "scripts" / "reindex_embeddings.py"
    spec = importlib.util.spec_from_file_location("reindex_embeddings", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_l_encodeur_declare_est_multilingue():
    assert "multilingual" in EMBEDDING_MODEL


def test_l_infra_construit_l_encodeur_declare(monkeypatch, tmp_path):
    import fastembed

    vus: list[str] = []

    class _FauxEncodeur:
        def __init__(self, model_name, cache_dir):
            vus.append(model_name)

    monkeypatch.setattr(fastembed, "TextEmbedding", _FauxEncodeur)
    monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path))
    from app.services.memory._infra import MemoryInfra

    MemoryInfra().encoder
    assert vus == [EMBEDDING_MODEL]


def test_la_dimension_declaree_est_celle_du_modele():
    """Le catalogue de fastembed est une table statique : aucun téléchargement."""
    from fastembed import TextEmbedding

    dims = {m["model"]: m["dim"] for m in TextEmbedding.list_supported_models()}
    assert dims[EMBEDDING_MODEL] == VECTOR_DIM


def test_l_image_docker_precharge_le_meme_modele():
    dockerfile = (_BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert EMBEDDING_MODEL in dockerfile
    assert "all-MiniLM-L6-v2" not in dockerfile


def test_la_base_de_connaissances_partage_la_dimension():
    from app.services import rag_service

    assert rag_service.VECTOR_DIM == VECTOR_DIM
    assert not hasattr(rag_service, "_VECTOR_DIM")


# ── Le ré-encodage ────────────────────────────────────────────────────────


class _Point:
    def __init__(self, id, payload):
        self.id, self.payload = id, payload


class _FauxClient:
    def __init__(self, contenu: dict[str, list[_Point]]):
        self.contenu = contenu
        self.ecrits: dict[str, list] = {}

    def collection_exists(self, name):
        return name in self.contenu

    def scroll(self, collection_name, limit, offset=None, with_payload=True, with_vectors=False):
        points = self.contenu[collection_name]
        debut = offset or 0
        lot = points[debut:debut + limit]
        suivant = debut + limit if debut + limit < len(points) else None
        return lot, suivant

    def upsert(self, collection_name, points):
        self.ecrits.setdefault(collection_name, []).extend(points)


class _FauxEncodeur:
    def embed(self, textes):
        for t in textes:
            yield [float(len(t))] * 3


def test_chaque_point_est_reencode_sous_le_meme_identifiant():
    script = _charger_script()
    client = _FauxClient({
        "memories": [_Point("a", {"content": "aime le thé"}), _Point("b", {"content": "vit à Rennes"})],
        "security_constraints": [_Point("c", {"rule": "jamais de mail le dimanche"})],
    })
    compte = script.reencoder(client, _FauxEncodeur(), lot=1)
    assert compte == {"memories": 2, "security_constraints": 1}
    ecrits = {p.id: p for p in client.ecrits["memories"]}
    assert set(ecrits) == {"a", "b"}
    assert ecrits["a"].vector == [float(len("aime le thé"))] * 3
    assert ecrits["a"].payload == {"content": "aime le thé"}
    assert client.ecrits["security_constraints"][0].vector == [float(len("jamais de mail le dimanche"))] * 3


def test_un_point_sans_texte_est_laisse_tel_quel():
    script = _charger_script()
    client = _FauxClient({"memories": [_Point("a", {"content": ""}), _Point("b", {"user_id": "u"})]})
    assert script.reencoder(client, _FauxEncodeur()) == {"memories": 0}
    assert client.ecrits == {}


def test_une_collection_absente_est_ignoree():
    script = _charger_script()
    client = _FauxClient({"memories": [_Point("a", {"content": "x"})]})
    assert script.reencoder(client, _FauxEncodeur()) == {"memories": 1}


def test_le_script_couvre_toutes_les_collections_vectorielles():
    """Chaque collection créée par le code a son champ de texte dans le script."""
    from app.services.memory._constants import (
        COLLECTION_CONSTRAINTS, COLLECTION_INTERACTIONS, COLLECTION_MEMORIES,
        COLLECTION_PREFERENCES,
    )
    from app.services.memory.indexing import PROFILE_COLLECTION
    from app.services.rag_service import _COLLECTION_KNOWLEDGE

    script = _charger_script()
    assert set(script.CHAMP_TEXTE) == {
        COLLECTION_MEMORIES, COLLECTION_CONSTRAINTS, COLLECTION_INTERACTIONS,
        COLLECTION_PREFERENCES, PROFILE_COLLECTION, _COLLECTION_KNOWLEDGE,
    }
