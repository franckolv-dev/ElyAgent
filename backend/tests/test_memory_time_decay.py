# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_memory_time_decay.py
# @brief      Regression test for MemoryManager._time_decay — accepts both
#             float Unix timestamps and ISO 8601 strings (bug observed
#             20 May 2026 at the bench session).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================
"""Regression — MemoryManager._time_decay accepts mixed timestamp formats.

Context
-------
On 20 May 2026 (Sprint 2.7 bench session), every ``memory_search`` for
Franck's account returned an empty result. The agent honestly reported
"BASE VIDE" while Qdrant actually held 799 entries.

Root cause: the write paths inside MemoryManager are inconsistent —
``_upsert`` stamps ``created_at`` with ``time.time()`` (float Unix
timestamp), while ``store_memory`` stamps with ``.isoformat()`` (string).
In production the 799 entries had ISO strings. The reader,
``_time_decay``, did ``time.time() - created_at_ts`` and crashed with
``unsupported operand type(s) for -: 'float' and 'str'``. The exception
was swallowed by the broad ``except Exception`` in
``get_relevant_memories``, returning an empty list.

These tests pin the fix: both formats must work, and an unparseable
string must degrade gracefully (return 1.0 = no decay) instead of
exploding.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.services.memory_manager import MemoryManager


# ──────────────────────────────────────────────────────────────────────
# Edge cases that bypass the actual decay computation
# ──────────────────────────────────────────────────────────────────────


def test_none_timestamp_returns_neutral_decay() -> None:
    assert MemoryManager._time_decay(None, 0.01) == 1.0


def test_zero_lambda_returns_neutral_decay() -> None:
    assert MemoryManager._time_decay(time.time(), 0.0) == 1.0
    assert MemoryManager._time_decay("2026-01-01T00:00:00+00:00", 0.0) == 1.0


# ──────────────────────────────────────────────────────────────────────
# Float Unix timestamps — the historical path
# ──────────────────────────────────────────────────────────────────────


def test_float_unix_timestamp_recent_means_no_decay_practically() -> None:
    """Just-created entry → decay factor ≈ 1.0 (within numeric noise)."""
    now = time.time()
    decay = MemoryManager._time_decay(now, lambda_decay=0.01)
    assert 0.999 < decay <= 1.0, f"got {decay}"


def test_float_unix_timestamp_30_days_old_decays_to_expected_value() -> None:
    """Lambda=0.01 / 30 days old → exp(-0.3) ≈ 0.7408."""
    thirty_days_ago = time.time() - 30 * 86400
    decay = MemoryManager._time_decay(thirty_days_ago, lambda_decay=0.01)
    expected = math.exp(-0.01 * 30)
    assert abs(decay - expected) < 1e-6


# ──────────────────────────────────────────────────────────────────────
# ISO 8601 strings — the path that crashed in prod
# ──────────────────────────────────────────────────────────────────────


def test_iso_string_with_tz_offset_is_accepted() -> None:
    """This is the exact format observed in Franck's production Qdrant."""
    iso = "2026-05-14T19:25:22.024553+00:00"
    decay = MemoryManager._time_decay(iso, lambda_decay=0.01)
    assert 0.0 < decay <= 1.0, f"got {decay}"


def test_iso_string_with_z_suffix_is_accepted() -> None:
    """Some external sources emit `Z` instead of `+00:00` — must also parse."""
    iso = "2026-05-14T19:25:22.024553Z"
    decay = MemoryManager._time_decay(iso, lambda_decay=0.01)
    assert 0.0 < decay <= 1.0, f"got {decay}"


def test_iso_string_30_days_old_decays_like_its_float_twin() -> None:
    """Same time, two formats → same decay factor (within numeric noise).
    Pinning this protects against future divergence between the two paths."""
    thirty_days_ago_dt = datetime.now(timezone.utc) - timedelta(days=30)
    iso = thirty_days_ago_dt.isoformat()
    flt = thirty_days_ago_dt.timestamp()

    decay_from_iso = MemoryManager._time_decay(iso, lambda_decay=0.01)
    decay_from_float = MemoryManager._time_decay(flt, lambda_decay=0.01)
    assert abs(decay_from_iso - decay_from_float) < 1e-6


# ──────────────────────────────────────────────────────────────────────
# Defensive — unparseable strings must NOT crash the whole search
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "garbage",
    [
        "",
        "not-a-date",
        "2026-13-99T99:99:99",
        "potato",
        "1234567890",  # looks like a Unix ts but is a str, not float
    ],
)
def test_unparseable_strings_degrade_to_no_decay(garbage: str) -> None:
    """Returning 1.0 (no decay) is the safe default: the offending entry
    keeps its raw vector score and isn't penalised. The whole search
    keeps working for all OTHER entries."""
    decay = MemoryManager._time_decay(garbage, lambda_decay=0.01)
    assert decay == 1.0, f"garbage={garbage!r} → expected 1.0, got {decay}"


# ──────────────────────────────────────────────────────────────────────
# Behavioural cross-check — lambdas behave monotonically
# ──────────────────────────────────────────────────────────────────────


def test_higher_lambda_decays_faster() -> None:
    """Sanity check: λ=0.05 (interactions) decays faster than λ=0.01 (memories)
    at the same age. Documents the policy difference between collections."""
    thirty_days_ago = time.time() - 30 * 86400
    soft = MemoryManager._time_decay(thirty_days_ago, lambda_decay=0.01)
    hard = MemoryManager._time_decay(thirty_days_ago, lambda_decay=0.05)
    assert hard < soft, f"λ=0.05 should decay faster than λ=0.01 (got {hard} vs {soft})"
