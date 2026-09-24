# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/_constants.py
# @brief      Constants shared across the typed memory stores.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.3.0
# =============================================================================
"""Shared constants for the typed memory subpackage."""

from __future__ import annotations

# Qdrant collection names — kept identical to the pre-Sprint-2.5 names so the
# 2,764 existing vectors in production remain readable without migration.
COLLECTION_MEMORIES = "memories"
COLLECTION_CONSTRAINTS = "security_constraints"
COLLECTION_INTERACTIONS = "interactions"
COLLECTION_PREFERENCES = "user_profile"

# ⚠️ CE QUE ÇA CORRIGE (ménage du 02/09/2026) : il y avait ici un
# `COLLECTION_PROCEDURES = "procedures"`, index sémantique prévu au Sprint 2.5
# au-dessus de la table SQL du même nom. La moisson n'a jamais été livrée, le
# `ProceduralStore` est parti en stub, et la lecture `procedural` a finalement
# été rebranchée le 02/08 sur le REGISTRE D'OUTILS (`_recall_procedural` →
# `rank_tools_for_capability`) — pas sur Qdrant. Restait `init_collections`,
# qui créait la collection à vide à chaque démarrage sans personne pour y
# écrire ni y lire. Si la voie procédurale reprend un jour un vrai magasin,
# c'est une décision d'architecture, pas une constante à remettre ici.

# L'encodeur de TOUT ce qui est vectorisé : souvenirs, interactions, profil,
# base de connaissances, et l'annuaire d'outils de `find_tool`.
#
# ⚠️ CE QUE ÇA CORRIGE (24/09/2026) : c'était `all-MiniLM-L6-v2`, un modèle
# ANGLAIS, devant des souvenirs et des demandes écrits en français. Mesuré :
# « prévisions météo pour demain à Nantes » ressemblait à `session_todo` (0,40)
# bien avant `weather_get` (0,14) ; la même phrase en anglais sortait
# `weather_get` premier. Sur 78 vrais appels de `find_tool`, le repli
# sémantique plaçait le bon outil en tête 4 fois ; le multilingue, 25 fois.
#
# Changer ce nom rend illisibles les vecteurs déjà en base : lancer ensuite
# `scripts/reindex_embeddings.py` dans le conteneur. Même dimension (384),
# donc les collections n'ont pas à être recréées.
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VECTOR_DIM = 384

# French + English stop-words — ignored during keyword overlap scoring.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "le",
        "la",
        "les",
        "de",
        "du",
        "des",
        "un",
        "une",
        "et",
        "en",
        "à",
        "au",
        "aux",
        "je",
        "tu",
        "il",
        "elle",
        "nous",
        "vous",
        "ils",
        "elles",
        "me",
        "te",
        "se",
        "que",
        "qui",
        "quoi",
        "où",
        "comment",
        "quand",
        "pourquoi",
        "ce",
        "cette",
        "ces",
        "mon",
        "ton",
        "son",
        "ma",
        "ta",
        "sa",
        "pas",
        "ne",
        "plus",
        "par",
        "sur",
        "sous",
        "dans",
        "avec",
        "pour",
        "sans",
        "est",
        "the",
        "a",
        "an",
        "of",
        "in",
        "is",
        "it",
        "to",
        "for",
        "on",
        "with",
        "are",
        "was",
        "were",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "did",
    }
)
