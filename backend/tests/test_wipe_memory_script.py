# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_wipe_memory_script.py
# @brief      Sprint 2.5 Jalon 5 — pin the safety semantics of the
#             clean-slate script. Verifies dry-run is the default and
#             that snapshot precedes wipe when --confirm is passed.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Safety tests for `scripts/wipe_memory_for_sprint_2_5.py`.

We do **not** spin up Qdrant or touch the SQLite file. The script's
external surface is a small set of helpers (`_qdrant_client`,
`_snapshot_collection`, `_recreate_collection`, `_truncate_sql_tables`,
`_wipe_fts_rows`) — we monkeypatch them and verify orchestration.

What's pinned :
  - The default mode is dry-run (no destructive call observed).
  - With --confirm, snapshot is called for every collection BEFORE any
    delete-or-recreate or SQL truncation. Snapshot failure aborts.
  - Empty collections skip snapshot but still get recreated.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# Make scripts/ importable for the test module.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import wipe_memory_for_sprint_2_5 as wipe  # noqa: E402


@pytest.fixture
def fake_qdrant(monkeypatch):
    """Fake Qdrant client that records ordered (op, collection) calls.

    Counts are pre-populated so the script sees non-empty collections
    and proceeds with the snapshot step.
    """
    calls: list[tuple[str, str]] = []

    class _FakeClient:
        def get_collection(self, name):
            class _Info:
                points_count = 5 if name == wipe.COLLECTION_MEMORIES else 0
                vectors_count = 5 if name == wipe.COLLECTION_MEMORIES else 0
            return _Info()

        def create_snapshot(self, collection_name):
            calls.append(("snapshot", collection_name))
            class _Snap:
                name = f"{collection_name}-snap.tar"
            return _Snap()

        def delete_collection(self, name):
            calls.append(("delete", name))

        def create_collection(self, name, vectors_config):
            calls.append(("create", name))

    monkeypatch.setattr(wipe, "_qdrant_client", lambda: _FakeClient())
    return calls


@pytest.fixture
def fake_sql(monkeypatch):
    """Bypass SQL truncation + FTS5 deletion (return zero rows)."""
    sql_calls: list[tuple[str, bool]] = []
    fts_calls: list[bool] = []

    async def fake_truncate(dry_run):
        sql_calls.append(("truncate", dry_run))
        return {"user_memory_logs": 0, "user_profiles": 0}

    async def fake_fts(dry_run):
        fts_calls.append(dry_run)
        return 0

    monkeypatch.setattr(wipe, "_truncate_sql_tables", fake_truncate)
    monkeypatch.setattr(wipe, "_wipe_fts_rows", fake_fts)
    return sql_calls, fts_calls


# ── Dry-run is the default ────────────────────────────────────────────


def test_dry_run_default_does_not_call_snapshot_or_delete(fake_qdrant, fake_sql) -> None:
    asyncio.run(wipe._amain(dry_run=True))

    # No mutation: no snapshot, no delete, no create.
    destructive = [c for c in fake_qdrant if c[0] in {"snapshot", "delete", "create"}]
    assert destructive == [], (
        f"Dry-run must touch nothing on Qdrant, observed: {destructive}"
    )

    # SQL truncate is called only in count mode (dry_run=True).
    sql_calls, fts_calls = fake_sql
    assert all(dr is True for _, dr in sql_calls), sql_calls
    assert all(dr is True for dr in fts_calls), fts_calls


# ── Confirm runs snapshot → wipe in order ─────────────────────────────


def test_confirm_snapshots_every_non_empty_before_recreate(fake_qdrant, fake_sql) -> None:
    asyncio.run(wipe._amain(dry_run=False))

    # The non-empty collection (memories) must be snapshotted.
    snapshot_targets = [name for op, name in fake_qdrant if op == "snapshot"]
    assert wipe.COLLECTION_MEMORIES in snapshot_targets

    # Every collection gets recreated (delete then create).
    create_targets = [name for op, name in fake_qdrant if op == "create"]
    for coll in wipe._COLLECTIONS_TO_WIPE:
        assert coll in create_targets

    # Snapshot of `memories` must appear BEFORE its delete.
    snap_idx = next(i for i, c in enumerate(fake_qdrant)
                    if c == ("snapshot", wipe.COLLECTION_MEMORIES))
    delete_idx = next(i for i, c in enumerate(fake_qdrant)
                      if c == ("delete", wipe.COLLECTION_MEMORIES))
    assert snap_idx < delete_idx, (
        "Snapshot must precede deletion (safety contract). "
        f"snap_idx={snap_idx}, delete_idx={delete_idx}"
    )


def test_empty_collections_skip_snapshot_but_get_recreated(fake_qdrant, fake_sql) -> None:
    """Empty collections : nothing to snapshot, but still recreate so
    they exist post-wipe with the canonical schema."""
    asyncio.run(wipe._amain(dry_run=False))

    snapshot_targets = [name for op, name in fake_qdrant if op == "snapshot"]
    # Only `memories` has points_count > 0 in the fake (see fixture).
    assert wipe.COLLECTION_PREFERENCES not in snapshot_targets
    assert wipe.COLLECTION_INTERACTIONS not in snapshot_targets

    create_targets = [name for op, name in fake_qdrant if op == "create"]
    assert wipe.COLLECTION_PREFERENCES in create_targets
    assert wipe.COLLECTION_INTERACTIONS in create_targets


def test_snapshot_failure_aborts_before_any_delete(monkeypatch, fake_sql) -> None:
    """If snapshot raises, we must NOT proceed to wipe. Hard-fail."""
    calls: list[tuple[str, str]] = []

    class _BadClient:
        def get_collection(self, name):
            class _Info:
                points_count = 10
                vectors_count = 10
            return _Info()

        def create_snapshot(self, collection_name):
            calls.append(("snapshot", collection_name))
            raise RuntimeError("disk full")

        def delete_collection(self, name):
            calls.append(("delete", name))

        def create_collection(self, name, vectors_config):
            calls.append(("create", name))

    monkeypatch.setattr(wipe, "_qdrant_client", lambda: _BadClient())

    with pytest.raises(RuntimeError, match="disk full"):
        asyncio.run(wipe._amain(dry_run=False))

    # No delete observed — snapshot failure prevented destruction.
    assert not any(op == "delete" for op, _ in calls)
    assert not any(op == "create" for op, _ in calls)
