# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_suite_audit_fond_et_journal.py
# @brief      Suite de l'audit du 02/09 (03/09) : tâches de fond tenues en
#             laisse, journal d'annulation qui lit le résultat, embeddings
#             sans verrou global.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Passe de vérification item par item du rapport d'audit (03/09/2026).

Quatre restes du plan « Corriger » et « Propre à Ely », tous petits, tous
nommés par la relecture du code et non par une hypothèse :

- ``maintenance_rapid.schedule_consolidation`` rendait un ``create_task`` nu
  que son seul appelant jetait — la dernière tâche de fond sans laisse ;
- le journal d'annulation enregistrait une action dont le résultat dit
  « Erreur … » (trou n°2 nommé dans ``compensation_registry``) ;
- une action passée en tâche de fond n'était jamais journalisée (trou n°1) ;
- ``REVERSIBLE_JOURNAL_ENABLED`` restait à False, donc les seize outils
  annulables l'étaient en principe seulement ;
- un seul ``asyncio.Lock`` sérialisait tous les embeddings du processus.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest


# ── La consolidation rapide part en laisse ───────────────────────────────────

@pytest.mark.asyncio
async def test_la_consolidation_rapide_passe_par_spawn(monkeypatch):
    import app.services.background_tasks as bg
    from app.services.memory import maintenance_rapid as mod

    vus: list[str] = []

    def _faux_spawn(coro, *, label=None, **kw):
        vus.append(label or "")
        coro.close()
        return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr(bg, "spawn", _faux_spawn)
    tache = mod.schedule_consolidation("conv-laisse", "user-laisse")

    assert tache is not None
    assert vus and "maintenance" in vus[0]


# ── Le journal ne journalise pas un échec ────────────────────────────────────

@pytest.mark.asyncio
async def test_un_resultat_en_erreur_n_est_pas_journalise(monkeypatch):
    from app.services import journal_service as js

    monkeypatch.setattr(js, "_enabled", lambda: True)

    def _pas_de_capture(*a, **k):
        raise AssertionError("la capture ne doit pas être tentée sur un échec")

    import app.services.compensation_registry as reg
    monkeypatch.setattr(reg, "get_compensation", _pas_de_capture)

    for texte in ("Erreur : fichier introuvable", "  ERROR: 404", "Échec de l'envoi", "echec"):
        assert await js.record_reversible(
            "drive_delete_file", {"file_id": "x"}, texte, "user-journal",
        ) is None


def test_la_regle_d_echec_est_celle_de_la_garde_anti_rejeu():
    """Une seule définition de « ce retour dit que l'action a échoué »."""
    from app.agent.replay_guard import _ECHEC_PREFIXES
    from app.services.journal_service import resultat_en_echec

    for p in _ECHEC_PREFIXES:
        assert resultat_en_echec(f"{p} : x") is True
    assert resultat_en_echec("✓ fichier supprimé") is False
    assert resultat_en_echec("") is False


# ── Une action partie en tâche de fond est journalisée à son terme ───────────

class _Ctx:
    def __init__(self):
        self.interactive = True
        self.conversation_id = "conv-fond"
        self.user_id = "user-fond"
        self.user_request = "supprime le fichier"


class _OutilLent:
    async def ainvoke(self, args):
        await asyncio.sleep(0.15)
        return "✓ supprimé"


@pytest.mark.asyncio
async def test_le_succes_d_une_tache_de_fond_declenche_la_journalisation(monkeypatch):
    from app.config import get_settings
    from app.services import long_running_tools as lrt

    monkeypatch.setattr(get_settings(), "long_tool_handoff_enabled", True)
    monkeypatch.setattr(get_settings(), "long_tool_soft_deadline_s", 0.02)

    async def _pas_de_livraison(job):
        return None

    monkeypatch.setattr(lrt, "_deliver_result", _pas_de_livraison)
    lrt._JOBS.clear()

    recus: list[str] = []

    async def _apres_succes(resultat: str) -> None:
        recus.append(resultat)

    result, notice = await lrt.invoke_with_handoff(
        _Ctx(), "drive_delete_file", _OutilLent(), {"file_id": "x"},
        on_success=_apres_succes,
    )
    assert result is None and notice  # parti en fond

    for _ in range(40):
        await asyncio.sleep(0.02)
        if recus:
            break
    assert recus == ["✓ supprimé"]


@pytest.mark.asyncio
async def test_l_echec_d_une_tache_de_fond_ne_journalise_rien(monkeypatch):
    from app.config import get_settings
    from app.services import long_running_tools as lrt

    monkeypatch.setattr(get_settings(), "long_tool_handoff_enabled", True)
    monkeypatch.setattr(get_settings(), "long_tool_soft_deadline_s", 0.02)

    async def _pas_de_livraison(job):
        return None

    monkeypatch.setattr(lrt, "_deliver_result", _pas_de_livraison)
    lrt._JOBS.clear()

    class _OutilQuiEchoue:
        async def ainvoke(self, args):
            await asyncio.sleep(0.15)
            raise RuntimeError("quota")

    recus: list[str] = []

    async def _apres_succes(resultat: str) -> None:
        recus.append(resultat)

    result, notice = await lrt.invoke_with_handoff(
        _Ctx(), "drive_delete_file", _OutilQuiEchoue(), {"file_id": "y"},
        on_success=_apres_succes,
    )
    assert result is None and notice
    await asyncio.sleep(0.3)
    assert recus == []


def test_la_passerelle_journalise_aussi_ce_qui_part_en_fond():
    """Le point unique d'exécution (``tool_gateway``) doit passer son
    ``on_success`` au relais : sans ça, la journalisation en fin de tâche de
    fond n'a aucun appelant."""
    import inspect

    from app.services import tool_gateway

    src = inspect.getsource(tool_gateway)
    assert "on_success=" in src
    assert src.index("invoke_with_handoff(") < src.index("on_success=")


# ── Le journal est ON par défaut ─────────────────────────────────────────────

def test_le_journal_d_annulation_est_actif_par_defaut():
    from app.config import Settings

    assert Settings.model_fields["reversible_journal_enabled"].default is True


# ── Les embeddings ne se sérialisent plus derrière un verrou global ──────────

class _EncodeurLent:
    def __init__(self):
        self.appels: list[str] = []

    def embed(self, textes):
        for t in textes:
            self.appels.append(t)
            time.sleep(0.12)
            yield SimpleNamespace(tolist=lambda: [0.0, 1.0])


@pytest.mark.asyncio
async def test_deux_textes_differents_s_embarquent_en_parallele():
    from app.services.memory._infra import MemoryInfra

    infra = MemoryInfra()
    enc = _EncodeurLent()
    infra._encoder = enc

    debut = time.monotonic()
    await asyncio.gather(infra.embed("alpha"), infra.embed("beta"), infra.embed("gamma"))
    duree = time.monotonic() - debut

    assert sorted(enc.appels) == ["alpha", "beta", "gamma"]
    assert duree < 0.30, f"sérialisés : {duree:.2f}s pour trois textes de 0,12 s"


@pytest.mark.asyncio
async def test_le_meme_texte_demande_cinq_fois_n_est_calcule_qu_une_fois():
    from app.services.memory._infra import MemoryInfra

    infra = MemoryInfra()
    enc = _EncodeurLent()
    infra._encoder = enc

    await asyncio.gather(*(infra.embed("même requête") for _ in range(5)))

    assert enc.appels == ["même requête"]
    assert not infra._embed_locks, "un verrou par texte ne doit pas survivre au calcul"
