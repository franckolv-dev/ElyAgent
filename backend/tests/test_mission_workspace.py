# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_workspace.py
# @brief      Missions autonomes J4 — workspace de mission : journal JSONL avec
#             rotation, CARNET.md atomique, injection contexte, branchements.
# @license    Elastic License 2.0
# =============================================================================
"""Missions autonomes J4 — pins du workspace (cadrage D5).

`data/missions/<id>/` = la mémoire de travail longue durée d'une mission
autonome : `artefacts/` (fichiers produits), `journal.jsonl` (append-only,
rotation), `CARNET.md` (relu à chaque planification, section Pause écrite
par le disjoncteur J3, leçons promues en mémoire durable à la complétion).
Flag OFF ou mission sans mandat actif ⇒ AUCUN fichier créé.
"""
from __future__ import annotations

import json as _json
import uuid

import pytest
import pytest_asyncio


@pytest.fixture
def _ws(tmp_path, monkeypatch):
    """Base workspace isolée + rotation basse pour les tests."""
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    monkeypatch.setenv("MISSIONS_JOURNAL_MAX_BYTES", "500")
    return tmp_path / "missions"


# ─────────────────────────────────────────────────────────────────────────
# Module pur — validation, journal, carnet
# ─────────────────────────────────────────────────────────────────────────


def test_workspace_dir_rejects_traversal(_ws):
    from app.services.mission_workspace import workspace_dir

    for bad in ("../x", "a/b", "", "a" * 80, "id with spaces", ".hidden"):
        with pytest.raises(ValueError):
            workspace_dir(bad)
    # un uuid4 passe
    assert workspace_dir(str(uuid.uuid4())).name


def test_ensure_workspace_creates_artefacts(_ws):
    from app.services.mission_workspace import ensure_workspace

    mid = str(uuid.uuid4())
    ws = ensure_workspace(mid)
    assert ws.is_dir() and (ws / "artefacts").is_dir()
    assert ws.parent == _ws


def test_journal_append_tail_and_rotation(_ws):
    from app.services.mission_workspace import (
        journal_append,
        read_journal_tail,
        workspace_dir,
    )

    mid = str(uuid.uuid4())
    journal_append(mid, {"tool": "t1", "ok": True})
    journal_append(mid, {"tool": "t2", "ok": False})
    tail = read_journal_tail(mid, n=10)
    assert [e["tool"] for e in tail] == ["t1", "t2"]
    assert all("ts" in e for e in tail)          # horodatage ajouté

    # Rotation : MAX=500 octets → quelques grosses lignes suffisent
    for i in range(20):
        journal_append(mid, {"tool": f"big{i}", "pad": "x" * 100})
    ws = workspace_dir(mid)
    assert (ws / "journal.1.jsonl").exists()      # archive créée
    assert (ws / "journal.jsonl").stat().st_size < 500 + 200
    # le tail lit le fichier courant sans casser
    assert read_journal_tail(mid, n=3)


def test_carnet_write_read_roundtrip_and_cap(_ws):
    from app.services.mission_workspace import read_carnet, write_carnet

    mid = str(uuid.uuid4())
    assert read_carnet(mid) is None
    write_carnet(mid, "# Carnet\n\ncontenu")
    assert read_carnet(mid).startswith("# Carnet")

    # Cap 64 Ko : la FIN est préservée (le récent prime)
    big = ("ancien\n" * 8000) + "FIN_RECENTE"
    write_carnet(mid, big)
    stored = read_carnet(mid)
    assert len(stored.encode()) <= 64 * 1024 + 100
    assert stored.endswith("FIN_RECENTE")


def test_carnet_append_section(_ws):
    from app.services.mission_workspace import (
        carnet_append_section,
        read_carnet,
        write_carnet,
    )

    mid = str(uuid.uuid4())
    write_carnet(mid, "# Carnet de bord\n\n## Leçons\n")
    carnet_append_section(mid, "Leçons", "- toujours vérifier le quota")
    carnet_append_section(mid, "Pause", "- pausée à 12h (seuil)")   # section absente → créée
    c = read_carnet(mid)
    assert "- toujours vérifier le quota" in c
    assert "## Pause" in c and "- pausée à 12h (seuil)" in c
    # la leçon est bien SOUS ## Leçons (avant ## Pause)
    assert c.index("vérifier le quota") < c.index("## Pause")


def test_init_carnet_idempotent(_ws):
    from app.services.mission_spec import parse_mission_spec
    from app.services.mission_workspace import init_carnet, read_carnet

    mid = str(uuid.uuid4())
    spec = parse_mission_spec(
        "version: 2\nmandate:\n  tools_allow: [youtube]\nsteps:\n  - id: s\n    do: x"
    )
    init_carnet(mid, "Chaîne YT", "gérer la chaîne", spec.mandate)
    c = read_carnet(mid)
    assert "# Carnet de bord" in c and "## Objectif" in c
    assert "## Mandat" in c and "youtube" in c
    assert "## Leçons" in c
    # idempotent : un carnet existant n'est PAS écrasé
    from app.services.mission_workspace import carnet_append_section
    carnet_append_section(mid, "Leçons", "- précieuse leçon")
    init_carnet(mid, "Chaîne YT", "gérer la chaîne", spec.mandate)
    assert "- précieuse leçon" in read_carnet(mid)


def test_carnet_context_block(_ws):
    from app.services.mission_workspace import carnet_context_block, write_carnet

    mid = str(uuid.uuid4())
    assert carnet_context_block(mid) is None      # pas de carnet → None
    write_carnet(mid, "# Carnet\n" + ("ligne ancienne\n" * 500) + "ETAT_RECENT")
    blk = carnet_context_block(mid, max_chars=1000)
    assert "CARNET DE BORD" in blk
    assert len(blk) <= 1000 + 100
    assert "ETAT_RECENT" in blk                   # la fin survit à la troncature
