# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/_constants.py
# @brief      Constants shared across the typed memory stores.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
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

# Sprint 2.5 — new collection holding the Qdrant index over the SQL
# `procedures` table (SQL = source of truth, this is just the semantic index).
COLLECTION_PROCEDURES = "procedures"

# all-MiniLM-L6-v2 output dimension — fastembed default
VECTOR_DIM = 384

# French + English stop-words — ignored during keyword overlap scoring.
STOP_WORDS: frozenset[str] = frozenset({
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "en", "à", "au",
    "aux", "je", "tu", "il", "elle", "nous", "vous", "ils", "elles", "me",
    "te", "se", "que", "qui", "quoi", "où", "comment", "quand", "pourquoi",
    "ce", "cette", "ces", "mon", "ton", "son", "ma", "ta", "sa", "pas", "ne",
    "plus", "par", "sur", "sous", "dans", "avec", "pour", "sans", "est",
    "the", "a", "an", "of", "in", "is", "it", "to", "for", "on", "with",
    "are", "was", "were", "be", "been", "have", "has", "had", "do", "did",
})
