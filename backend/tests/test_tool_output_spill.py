# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_output_spill.py
# @brief      Débordement des sorties d'outil vers fichier : une grande sortie
#             n'est plus tronquée mais conservée en entier, et le modèle peut
#             la pager au lieu de redemander la même donnée.
# @license    Elastic License 2.0
# =============================================================================
"""Contrat du débordement des sorties volumineuses.

Défaut d'origine : au-delà d'une borne, une sortie d'outil était COUPÉE et
le reste PERDU (page lue par l'extension Chrome à 8 000 caractères, sortie
archivée dans une mission à 5 000). Le modèle voyait le début, n'avait aucun
moyen d'obtenir la suite, relisait la même page et repayait la troncature.

Run with:
    cd backend && python -m pytest tests/test_tool_output_spill.py -v
"""
from __future__ import annotations

import os
import re
import time
import uuid

import pytest
import pytest_asyncio

from app.database import init_db

_ID_IN_NOTICE = re.compile(r'spill_id="([A-Za-z0-9_-]+)"')


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


@pytest.fixture(autouse=True)
def _spill_dir(tmp_path, monkeypatch):
    """Isole le répertoire de débordement (jamais le /tmp de la machine)."""
    monkeypatch.setenv("TOOL_OUTPUT_SPILL_DIR", str(tmp_path / "spill"))
    yield


def _ctx(user_id: str):
    from app.services.conversation_filters import get_filter
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import GatewayContext

    conv = f"conv-spill-{uuid.uuid4()}"
    return GatewayContext(
        user_id=user_id, conversation_id=conv,
        pii_filter=get_filter(conv), criticality_filter=SecurityFilter(),
        hitl=None, memory=None,
    )


class _PayloadTool:
    """Outil qui rend exactement ce qu'on lui a demandé de rendre."""

    name = "payload_tool"

    def __init__(self, payload: str):
        self._payload = payload

    async def ainvoke(self, args):
        return self._payload


async def _run(user_id: str, payload: str) -> str:
    from app.services.tool_gateway import execute_tool_call

    msg = await execute_tool_call(
        _ctx(user_id),
        {"name": "payload_tool", "args": {}, "id": "tc-1"},
        {"payload_tool": _PayloadTool(payload)},
    )
    return msg["content"]


# ── Passerelle ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_petite_sortie_passe_inchangee():
    petite = "resultat court, rien a deborder"
    assert await _run("u-petit", petite) == petite


@pytest.mark.asyncio
async def test_une_grande_sortie_est_remplacee_par_le_bloc_et_le_fichier_contient_tout():
    from app.services.tool_output_spill import read_slice, spill_threshold_chars

    grande = "".join(f"ligne {i:06d}\n" for i in range(4000))
    assert len(grande) > spill_threshold_chars()

    contenu = await _run("u-grand", grande)

    assert grande not in contenu
    assert str(len(grande)) in contenu           # la TAILLE réelle est annoncée
    assert grande[:200] in contenu               # un APERÇU du début est rendu
    assert "tool_output_read" in contenu         # la marche à suivre est dite

    spill_id = _ID_IN_NOTICE.search(contenu).group(1)
    # Le fichier porte TOUT le texte, pas seulement l'aperçu : on le remonte
    # tranche par tranche, exactement comme le ferait le modèle.
    derniere = ""
    for offset in range(0, len(grande), 10_000):
        derniere = read_slice(spill_id, offset, 10_000, user_id="u-grand")
        assert grande[offset:offset + 10_000] in derniere
    assert "fin du débordement" in derniere


# ── Outil de lecture ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_l_outil_de_lecture_rend_la_tranche_demandee():
    from app.agent.tools.tool_output_spill_tool import tool_output_read
    from app.services.tool_output_spill import owner_scope

    grande = "".join(f"{i:08d}" for i in range(4000))   # 32 000 caractères
    contenu = await _run("u-tranche", grande)
    spill_id = _ID_IN_NOTICE.search(contenu).group(1)

    with owner_scope("u-tranche"):
        tranche = tool_output_read.invoke(
            {"spill_id": spill_id, "offset": 1000, "length": 500}
        )
    assert grande[1000:1500] in tranche


@pytest.mark.asyncio
async def test_un_utilisateur_ne_lit_pas_le_debordement_d_un_autre():
    from app.agent.tools.tool_output_spill_tool import tool_output_read
    from app.services.tool_output_spill import owner_scope

    secret = "SECRET-DE-ALICE " * 2000
    contenu = await _run("u-alice", secret)
    spill_id = _ID_IN_NOTICE.search(contenu).group(1)

    with owner_scope("u-bob"):
        reponse = tool_output_read.invoke({"spill_id": spill_id, "offset": 0, "length": 500})
    assert "SECRET-DE-ALICE" not in reponse

    with owner_scope("u-alice"):
        sienne = tool_output_read.invoke({"spill_id": spill_id, "offset": 0, "length": 500})
    assert "SECRET-DE-ALICE" in sienne


def test_une_traversee_de_chemin_est_refusee():
    from app.agent.tools.tool_output_spill_tool import tool_output_read
    from app.services.tool_output_spill import owner_scope

    with owner_scope("u-traversee"):
        for tentative in ("../../etc/passwd", "..", "a/b", "x\x00y", ""):
            reponse = tool_output_read.invoke(
                {"spill_id": tentative, "offset": 0, "length": 100}
            )
            assert "root:" not in reponse
            assert "identifiant" in reponse.lower() or "introuvable" in reponse.lower()


# ── Ménage ───────────────────────────────────────────────────────────────────

def test_la_purge_retire_les_vieux_fichiers_et_garde_les_recents():
    from app.services.tool_output_spill import purge_old, read_slice, write_spill

    vieux_id, vieux_path = write_spill("x" * 100, user_id="u-purge", tool_name="t")
    recent_id, _ = write_spill("y" * 100, user_id="u-purge", tool_name="t")

    ancien = time.time() - 3 * 24 * 3600
    os.utime(vieux_path, (ancien, ancien))

    assert purge_old(max_age_s=24 * 3600, force=True) == 1
    with pytest.raises(FileNotFoundError):
        read_slice(vieux_id, 0, 10, user_id="u-purge")
    assert "y" in read_slice(recent_id, 0, 10, user_id="u-purge")


# ── Le chemin des missions ───────────────────────────────────────────────────

@pytest.fixture
def _registre_bouchon(monkeypatch):
    """Installe un registre d'outils qui ne contient que le payload tool."""

    class _FakeRegistry:
        def __init__(self, tools):
            self.all_tools = tools

    def _install(nom: str, payload: str):
        outil = _PayloadTool(payload)
        outil.name = nom
        monkeypatch.setattr("app.skills.get_skill_registry",
                            lambda: _FakeRegistry([outil]))

    return _install


@pytest.mark.asyncio
async def test_une_mission_recoit_la_sortie_entiere_pas_un_apercu(_registre_bouchon):
    """⚠️ 02/09/2026 — l'évaluateur d'étape et l'expansion `foreach` sont des
    PROMPTS : ils ne peuvent pas appeler `tool_output_read`. Un débordement sur
    ce chemin ne masque pas l'affichage, il DÉTRUIT la donnée (archivée dans
    MissionStepRun.output, relue par `_foreach_source`)."""
    from app.agent.missions import nodes

    grande = "".join(f"societe {i:05d} — contact@ex{i}.fr\n" for i in range(1200))
    _registre_bouchon("notes_list", grande)

    sortie, ok = await nodes.dispatch_tool(
        "notes_list", {}, "tc-mission", user_id="u-mission-spill",
    )
    assert ok
    assert sortie == grande, "la mission a reçu un aperçu au lieu de la sortie"
    assert "tool_output_read" not in sortie


# ── La boucle qui ne termine pas ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_lecture_a_la_borne_maximale_ne_redeborde_pas():
    """⚠️ 02/09/2026 — la tranche maximale annoncée (20 000) dépassait le seuil
    de débordement (12 000) : la réponse de `tool_output_read` redébordait, avec
    un nouvel identifiant et un fichier de plus. Un modèle qui suit le maximum
    documenté ne s'arrête jamais."""
    from app.agent.tools.tool_output_spill_tool import tool_output_read
    from app.services.tool_gateway import execute_tool_call
    from app.services.tool_output_spill import write_spill

    grande = "".join(f"{i:08d}" for i in range(10_000))   # 80 000 caractères
    spill_id, _ = write_spill(grande, user_id="u-boucle", tool_name="payload_tool")

    msg = await execute_tool_call(
        _ctx("u-boucle"),
        {"name": "tool_output_read",
         "args": {"spill_id": spill_id, "offset": 0, "length": 999_999},
         "id": "tc-lecture"},
        {"tool_output_read": tool_output_read},
    )
    contenu = msg["content"]
    assert "sortie volumineuse" not in contenu, (
        "la lecture d'un débordement a elle-même débordé — boucle infinie"
    )
    assert _ID_IN_NOTICE.search(contenu) is None


# ── Joignabilité depuis le profil des petites fenêtres ───────────────────────

def test_l_outil_de_pagination_est_joignable_depuis_le_profil_compact():
    """⚠️ 02/09/2026 — `compact` est le profil des fenêtres étroites, donc celui
    qui déclenche le plus le débordement. Sans l'outil dans sa liaison, le bloc
    ORDONNE au modèle d'appeler ce qu'il n'a pas : une impasse."""
    from app.agent.toolset_profiles import resolve_profile_tools
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    joignables = {
        t.name for t in resolve_profile_tools("compact", get_skill_registry().all_tools)
    }
    assert "tool_output_read" in joignables


# ── Idempotence ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_rejeu_idempotent_deborde_comme_le_premier_appel(monkeypatch):
    """⚠️ 02/09/2026 — le résultat mémorisé était rendu EN ENTIER : la même
    action rendait un aperçu au premier appel et 60 000 caractères au second."""
    from app.config import get_settings

    grande = "".join(f"memorise {i:06d}\n" for i in range(4000))
    monkeypatch.setattr(get_settings(), "trust_substrate_enabled", True)

    async def _cache_plein(_tool_name, _fp):
        return grande

    monkeypatch.setattr("app.services.idempotency_store.check_idempotent",
                        _cache_plein)

    contenu = await _run("u-idem", "peu importe")
    assert grande not in contenu
    assert "tool_output_read" in contenu
