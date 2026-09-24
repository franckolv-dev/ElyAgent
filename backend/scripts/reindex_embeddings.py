#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/scripts/reindex_embeddings.py
# @brief      Ré-encode chaque vecteur de Qdrant avec l'encodeur courant,
#             sous le même identifiant et le même payload.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""À lancer une fois après un changement de ``EMBEDDING_MODEL`` (24/09/2026).

Les vecteurs en base ont été calculés par l'ancien encodeur : une requête
encodée par le nouveau ne les retrouve plus, sans aucune erreur. Ce script
relit chaque point, ré-encode son texte et le réécrit sous le même identifiant.
Idempotent : le relancer ré-encode simplement une seconde fois.

Usage, dans le conteneur backend (le modèle est dans le cache de l'image) :

    docker exec -w /app physicalagent-master-backend-1 \
        /app/.venv/bin/python scripts/reindex_embeddings.py

Ordre de grandeur mesuré le 24/09 : 17 000 points, ~11 ms par texte.
"""
from __future__ import annotations

import logging
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from app.services.memory._constants import (  # noqa: E402
    COLLECTION_CONSTRAINTS, COLLECTION_INTERACTIONS, COLLECTION_MEMORIES,
    COLLECTION_PREFERENCES,
)
from app.services.memory.indexing import PROFILE_COLLECTION  # noqa: E402
from app.services.rag_service import _COLLECTION_KNOWLEDGE  # noqa: E402

logger = logging.getLogger("reindex_embeddings")

# Le champ du payload qui porte le texte encodé, collection par collection.
CHAMP_TEXTE: dict[str, str] = {
    COLLECTION_MEMORIES: "content",
    COLLECTION_INTERACTIONS: "content",
    COLLECTION_PREFERENCES: "content",
    PROFILE_COLLECTION: "content",
    _COLLECTION_KNOWLEDGE: "content",
    COLLECTION_CONSTRAINTS: "rule",
}


def reencoder(client, encoder, lot: int = 256) -> dict[str, int]:
    """Ré-encode chaque collection connue. Rend le nombre de points réécrits."""
    from qdrant_client.models import PointStruct

    compte: dict[str, int] = {}
    for collection, champ in CHAMP_TEXTE.items():
        if not client.collection_exists(collection):
            continue
        compte[collection] = 0
        suivant = None
        while True:
            points, suivant = client.scroll(
                collection_name=collection, limit=lot, offset=suivant,
                with_payload=True, with_vectors=False,
            )
            avec_texte = [p for p in points if (p.payload or {}).get(champ)]
            if avec_texte:
                vecteurs = encoder.embed([p.payload[champ] for p in avec_texte])
                client.upsert(
                    collection_name=collection,
                    points=[
                        PointStruct(id=p.id, vector=list(v), payload=p.payload)
                        for p, v in zip(avec_texte, vecteurs)
                    ],
                )
                compte[collection] += len(avec_texte)
            if suivant is None:
                break
        logger.info("%s : %d point(s) ré-encodé(s)", collection, compte[collection])
    return compte


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.services.memory._constants import EMBEDDING_MODEL
    from app.services.memory._infra import get_memory_infra

    infra = get_memory_infra()
    logger.info("encodeur : %s", EMBEDDING_MODEL)
    debut = time.monotonic()
    compte = reencoder(infra.client, infra.encoder)
    logger.info(
        "terminé : %d point(s) en %.0f s", sum(compte.values()), time.monotonic() - debut,
    )


if __name__ == "__main__":
    main()
