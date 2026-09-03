# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_stdio_sandbox.py
# @brief      Client MCP v2 — J5 : sandbox des serveurs stdio (launcher/rlimits)
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests J5 : confinement du spawn stdio.

Couvre : construction de l'argv launcher, résolution du profil, PREUVE qu'une
rlimit est réellement appliquée à travers execvp (NOFILE partout, AS sous Linux),
PREUVE du kill de l'arbre de processus, rétrocompat stricte (flag OFF ⇒ spawn
legacy au byte près), et la migration 0017."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

from app.services import mcp_client
from app.services.mcp_client import _StdioConnection, _resolve_sandbox_profile
from app.services.mcp_stdio_launcher import build_launcher_argv

_POSIX = os.name != "nt"
_DARWIN = sys.platform == "darwin"


# ── build_launcher_argv (unitaire pur) ───────────────────────────────────────

def test_build_launcher_argv_shape():
    exe, args = build_launcher_argv(
        "npx", ["-y", "pkg"],
        profile={"mem_bytes": 100, "nofile": 50, "fsize_bytes": 200},
        pgid_file="/tmp/pg")
    assert exe == sys.executable
    assert args[0] == "-S"
    assert args[1].endswith("mcp_stdio_launcher.py")
    assert "--mem-bytes" in args and "100" in args
    assert "--nofile" in args and "50" in args
    assert "--fsize" in args and "200" in args
    assert "--pgid-file" in args
    # La commande réelle vient après le séparateur « -- ».
    sep = args.index("--")
    assert args[sep + 1:] == ["npx", "-y", "pkg"]


def test_build_launcher_argv_omits_zero_limits():
    _, args = build_launcher_argv("x", [], profile={"mem_bytes": 0, "nofile": 0, "fsize_bytes": 0}, pgid_file="")
    assert "--mem-bytes" not in args
    assert "--nofile" not in args
    assert "--pgid-file" not in args
    assert args[args.index("--") + 1:] == ["x"]


# ── _resolve_sandbox_profile ─────────────────────────────────────────────────

def _settings(**kw):
    base = dict(mcp_stdio_sandbox_enabled=True, mcp_stdio_sandbox_mem_bytes=512,
                mcp_stdio_sandbox_nofile=256, mcp_stdio_sandbox_fsize_bytes=64)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_resolve_profile_none_when_flag_off(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(mcp_stdio_sandbox_enabled=False))
    assert _resolve_sandbox_profile(types.SimpleNamespace(sandbox_profile_json=None)) is None


def test_resolve_profile_defaults(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: _settings())
    p = _resolve_sandbox_profile(types.SimpleNamespace(sandbox_profile_json=None))
    assert p == {"mem_bytes": 512, "nofile": 256, "fsize_bytes": 64}


def test_resolve_profile_override_bounded(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: _settings())
    srv = types.SimpleNamespace(sandbox_profile_json='{"mem_bytes": 1024, "nofile": -5, "bogus": 9}')
    p = _resolve_sandbox_profile(srv)
    assert p["mem_bytes"] == 1024     # override valide appliqué
    assert p["nofile"] == 256         # valeur ≤ 0 ignorée → défaut
    assert "bogus" not in p           # clé inconnue ignorée


def test_resolve_profile_invalid_json_falls_back(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: _settings())
    p = _resolve_sandbox_profile(types.SimpleNamespace(sandbox_profile_json="{not json"))
    assert p == {"mem_bytes": 512, "nofile": 256, "fsize_bytes": 64}


def test_resolve_profile_rejects_booleans(monkeypatch):
    # En Python isinstance(True, int) est vrai — un booléen ne doit PAS devenir
    # une limite (True ⇒ 1 octet casserait tout).
    monkeypatch.setattr("app.config.get_settings", lambda: _settings())
    srv = types.SimpleNamespace(sandbox_profile_json='{"mem_bytes": true, "nofile": false}')
    p = _resolve_sandbox_profile(srv)
    assert p["mem_bytes"] == 512   # bool refusé → défaut
    assert p["nofile"] == 256


# ── PREUVE : une rlimit est réellement appliquée à travers execvp ────────────

@pytest.mark.skipif(not _POSIX, reason="rlimits POSIX uniquement")
def test_launcher_enforces_nofile_across_execvp():
    prog = "import resource; print(resource.getrlimit(resource.RLIMIT_NOFILE)[0])"
    exe, args = build_launcher_argv(
        sys.executable, ["-c", prog],
        profile={"mem_bytes": 0, "nofile": 123, "fsize_bytes": 0}, pgid_file="")
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=30)
    assert r.stdout.strip() == "123", f"stderr={r.stderr}"


@pytest.mark.skipif(not _POSIX or _DARWIN, reason="RLIMIT_AS non fiable sur macOS")
def test_launcher_enforces_as_on_linux():
    val = 600 * 1024 * 1024
    prog = "import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0])"
    exe, args = build_launcher_argv(
        sys.executable, ["-c", prog],
        profile={"mem_bytes": val, "nofile": 0, "fsize_bytes": 0}, pgid_file="")
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=30)
    assert r.stdout.strip() == str(val), f"stderr={r.stderr}"


def test_launcher_exec_failure_exit_code():
    # Commande introuvable → exit 127 + message clair sur stderr (pas de crash).
    exe, args = build_launcher_argv(
        "ce-binaire-nexiste-pas-xyz", [], profile={}, pgid_file="")
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 127
    assert "exec" in r.stderr.lower()


# ── PREUVE : kill de l'arbre de processus ────────────────────────────────────

@pytest.mark.skipif(not _POSIX, reason="setsid/killpg POSIX uniquement")
@pytest.mark.asyncio
async def test_kill_process_group_reaps_descendants():
    fd, pgid_file = tempfile.mkstemp(prefix="ely-test-pgid-")
    os.close(fd)
    fd2, gc_file = tempfile.mkstemp(prefix="ely-test-gc-")
    os.close(fd2)
    # Le parent fork un PETIT-ENFANT (le vrai risque d'orphelin), écrit son PID
    # puis dort. Les deux vivent dans le groupe créé par le setsid du launcher.
    prog = (
        "import os, sys, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    time.sleep(60)\n"
        "else:\n"
        "    open(sys.argv[1], 'w').write(str(pid))\n"
        "    time.sleep(60)\n"
    )
    exe, args = build_launcher_argv(sys.executable, ["-c", prog, gc_file], profile={}, pgid_file=pgid_file)
    proc = subprocess.Popen([exe, *args])
    try:
        pgid = gc_pid = 0
        for _ in range(50):
            ptxt = Path(pgid_file).read_text().strip() if os.path.getsize(pgid_file) else ""
            gtxt = Path(gc_file).read_text().strip() if os.path.getsize(gc_file) else ""
            if ptxt and gtxt:
                pgid, gc_pid = int(ptxt), int(gtxt)
                break
            await asyncio.sleep(0.1)
        assert pgid > 1 and gc_pid > 1, "launcher/petit-enfant non démarrés"
        os.kill(gc_pid, 0)  # petit-enfant vivant

        await mcp_client._terminate_pgroup(pgid, grace=1.0)
        try:
            proc.wait(timeout=5)  # reap le parent direct (évite le zombie)
        except Exception:
            pass
        # Le petit-enfant (orphelin réel) doit être mort + reapé par init.
        for _ in range(50):
            try:
                os.kill(gc_pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("le petit-enfant a survécu au kill-arbre")
    finally:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        for f in (pgid_file, gc_file):
            try:
                os.unlink(f)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_terminate_pgroup_never_kills_backend_group():
    # Garde anti-suicide : on ne tue jamais le groupe du backend lui-même.
    import os as _os
    await mcp_client._terminate_pgroup(_os.getpgrp())  # ne doit rien faire
    await mcp_client._terminate_pgroup(0)
    await mcp_client._terminate_pgroup(1)


# ── Rétrocompat & branche sandbox via le harnais fake-MCP ────────────────────

@pytest.fixture
def fake_mcp(monkeypatch):
    """Fake `mcp` enregistrant les kwargs de StdioServerParameters."""
    rec: dict = {}

    class _CM:
        def __init__(self, val):
            self._val = val

        async def __aenter__(self):
            return self._val

        async def __aexit__(self, *a):
            return False

    class _Session:
        async def initialize(self):
            pass

    def _stdio_client(params):
        return _CM(("r", "w"))

    def _session(r, w):
        return _CM(_Session())

    class _Params:
        def __init__(self, command, args, env, cwd=None, **extra):
            rec["command"] = command
            rec["args"] = args
            rec["env"] = env
            rec["cwd"] = cwd
            rec["has_cwd_kw"] = "cwd"

    mcp_root = types.ModuleType("mcp")
    mcp_root.ClientSession = _session
    mcp_root.StdioServerParameters = _Params
    mod_client = types.ModuleType("mcp.client")
    mod_stdio = types.ModuleType("mcp.client.stdio")
    mod_stdio.stdio_client = _stdio_client
    monkeypatch.setitem(sys.modules, "mcp", mcp_root)
    monkeypatch.setitem(sys.modules, "mcp.client", mod_client)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", mod_stdio)
    return rec


@pytest.mark.asyncio
async def test_flag_off_spawn_is_legacy(fake_mcp):
    # sandbox=None ⇒ aucune réécriture : commande/argv d'origine, cwd None,
    # aucun fichier sentinelle créé.
    conn = _StdioConnection("fake-cmd --arg", env={"PATH": "/x"}, sandbox=None)
    await conn._connect()
    await conn.close()
    assert fake_mcp["command"] == "fake-cmd"
    assert fake_mcp["args"] == ["--arg"]
    assert fake_mcp["env"] == {"PATH": "/x"}
    assert fake_mcp["cwd"] is None
    assert conn._pgid_file is None


@pytest.mark.asyncio
async def test_flag_on_uses_launcher(fake_mcp):
    conn = _StdioConnection(
        "fake-cmd", env={"PATH": "/x"}, args=["--flag"],
        sandbox={"mem_bytes": 256, "nofile": 64, "fsize_bytes": 32}, cwd="/work")
    await conn._connect()
    pgid_file = conn._pgid_file
    assert pgid_file and os.path.exists(pgid_file)
    await conn.close()
    # Le SDK reçoit l'interpréteur + le launcher, la vraie commande après « -- ».
    assert fake_mcp["command"] == sys.executable
    assert fake_mcp["args"][0] == "-S"
    assert fake_mcp["args"][1].endswith("mcp_stdio_launcher.py")
    sep = fake_mcp["args"].index("--")
    assert fake_mcp["args"][sep + 1:] == ["fake-cmd", "--flag"]
    assert fake_mcp["cwd"] == "/work"
    # close() a purgé la sentinelle.
    assert not os.path.exists(pgid_file)


# ── Migration 0017 ───────────────────────────────────────────────────────────

def test_migration_0017_adds_column_idempotent():
    import importlib.util

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0017_mcp_stdio_sandbox.py"
    spec = importlib.util.spec_from_file_location("m0017", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    eng = sa.create_engine("sqlite://")
    with eng.connect() as con:
        con.exec_driver_sql("CREATE TABLE mcp_servers (id TEXT PRIMARY KEY, slug TEXT)")
        m.op = Operations(MigrationContext.configure(con))
        m.upgrade()
        cols = {c["name"] for c in sa.inspect(con).get_columns("mcp_servers")}
        assert "sandbox_profile_json" in cols
        m.upgrade()  # idempotent : ne lève pas
