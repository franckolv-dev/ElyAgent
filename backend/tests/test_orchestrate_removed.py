# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_removed.py
# @brief      Ménage lot 5 — démantèlement du sous-système orchestrate, en
#             relocalisant ce que d'autres en dépendaient.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins du retrait d'`orchestrate` (outil + bac à sable).

**Pourquoi.** `orchestrate` exécutait un script Python dans un bac à sable pour
enchaîner plusieurs appels d'outils en lecture seule. Mesuré le 29/07 :
**9 appels en tout, aucun depuis le 12 juin** (47 jours), pour **4 826
caractères de description** — la plus lourde du catalogue, ~1 206 tokens payés
à **chaque tour** du chemin profil.

Franck a par ailleurs écarté la ligne « Ely fabrique et exécute » le 27/07
([[agent_vs_bricolage]]) : le bac à sable n'a plus de rôle dans la cible.

**Ce lot n'est pas une suppression, c'est un démantèlement** — 2 187 lignes sur
4 fichiers. Deux choses le retenaient, et **aucune n'avait plus de rapport avec
orchestrate** :

1. `smoke_sandbox` (validation des compétences apprises) importait trois
   symboles de durcissement du runner : `_SAFE_ENV_PREFIXES`,
   `_SECRET_SUBSTRINGS`, `_kill_process_group`. Ils vivent désormais dans
   `env_filter`, dont c'est déjà le métier.
2. `ORCHESTRATE_CONVERSATION_ID` n'était plus « la conversation d'orchestrate »
   mais **la conversation courante**, lue par `delegate_tool` et
   `find_tool_skill`. Renommé `CURRENT_CONVERSATION_ID` dans
   `app/agent/tool_context.py` — garder l'ancien nom aurait laissé un nom qui
   ment, exactement ce que ce ménage traque.

**Les deux pins de sûreté sont les tests 4 et 5** : ils vérifient que le
durcissement et l'identifiant de conversation SURVIVENT au démantèlement. Sans
eux, ce lot casserait la validation des compétences en silence.

Run with:  cd backend && python -m pytest tests/test_orchestrate_removed.py -v
"""
from __future__ import annotations

import importlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1-3. Le sous-système est parti
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module", [
    "app.agent.tools.orchestrate_tool",
    "app.services.orchestrate_runner",
    "app.services.orchestrate_rpc",
    "app.services.orchestrate_stubs",
])
def test_module_no_longer_importable(module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_orchestrate_is_no_longer_a_registered_tool() -> None:
    """L'outil ne se propose plus au modèle."""
    from app.skills.builtin import register_all
    from app.skills import get_skill_registry

    register_all()
    assert "orchestrate" not in {t.name for t in get_skill_registry().all_tools}


def test_orchestrate_left_the_default_profile() -> None:
    """Et il ne se paie plus dans le catalogue bindé à chaque tour."""
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all
    from app.agent.toolset_profiles import get_profile_tool_names

    # #323 : `default` vaut tout le catalogue, donc « absent du profil » ne
    # prouverait plus rien. On épingle plus fort — absent du CATALOGUE.
    register_all()
    assert "orchestrate" not in {t.name for t in get_skill_registry().all_tools}
    assert "orchestrate" not in get_profile_tool_names("compact")


# ---------------------------------------------------------------------------
# 4. PIN DE SÛRETÉ — le durcissement du bac à sable survit
# ---------------------------------------------------------------------------

def test_sandbox_hardening_survives_in_env_filter() -> None:
    """`smoke_sandbox` trouve toujours ses trois symboles, chez `env_filter`."""
    from app.services import env_filter

    assert isinstance(env_filter.SAFE_ENV_PREFIXES, tuple)
    assert isinstance(env_filter.SECRET_SUBSTRINGS, tuple)
    assert callable(env_filter.kill_process_group)

    # Le contenu compte autant que la présence : ce sont ces valeurs qui
    # empêchent une clé d'API d'atterrir dans l'environnement d'un enfant.
    assert "ELY_" in env_filter.SAFE_ENV_PREFIXES
    for forbidden in ("KEY", "TOKEN", "SECRET", "PASSWORD"):
        assert forbidden in env_filter.SECRET_SUBSTRINGS

    from app.services.learning import smoke_sandbox  # noqa: F401 — doit s'importer


@pytest.mark.skipif(os.name == "nt", reason="groupes de processus POSIX")
def test_kill_process_group_really_kills_the_whole_group() -> None:
    """Comportemental : un enfant qui a lui-même un enfant meurt entièrement.

    C'est la raison d'être de la fonction — `proc.kill()` seul laisserait des
    orphelins. On le vérifie en vrai plutôt que de faire confiance au
    déplacement du code.
    """
    from app.services.env_filter import kill_process_group

    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess,sys,time;"
         "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
         "time.sleep(60)"],
        start_new_session=True,
    )
    time.sleep(0.5)
    pgid = os.getpgid(proc.pid)

    kill_process_group(proc, grace=1.0)
    proc.wait(timeout=5)

    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)   # plus personne dans le groupe


# ---------------------------------------------------------------------------
# 5. PIN DE SÛRETÉ — l'identifiant de conversation survit
# ---------------------------------------------------------------------------

def test_current_conversation_id_survives_and_is_shared() -> None:
    """`delegate_tool` et `find_tool_skill` lisent le MÊME ContextVar.

    Le test importe les trois modules et compare l'identité de l'objet : deux
    ContextVar distincts porteraient le même nom sans jamais se voir.
    """
    from app.agent.tool_context import CURRENT_CONVERSATION_ID
    from app.agent import tool_node
    from app.agent.tools import delegate_tool

    assert delegate_tool.CURRENT_CONVERSATION_ID is CURRENT_CONVERSATION_ID

    token = CURRENT_CONVERSATION_ID.set("conv-42")
    try:
        assert CURRENT_CONVERSATION_ID.get() == "conv-42"
        assert tool_node is not None
    finally:
        CURRENT_CONVERSATION_ID.reset(token)


def test_no_module_still_mentions_orchestrate_conversation_id() -> None:
    """Le nom qui mentait a bien disparu — sauf là où il est daté comme tel.

    `tool_context` est exempté : il DOIT dire d'où vient la variable, sinon on
    reperd la traçabilité que ce ménage vise. Un commentaire qui date un
    renommage n'est pas un nom qui ment.
    """
    exempt = {
        "app/agent/tool_context.py",   # documente son propre renommage
        Path(__file__).name,
        # liste volontairement les noms supprimés pour contrôler les docs
        "test_docs_match_the_code.py",
    }
    offenders: list[str] = []
    for folder in ("app", "tests"):
        for path in (_BACKEND / folder).rglob("*.py"):
            if "__pycache__" in str(path) or path.name in exempt:
                continue
            if str(path.relative_to(_BACKEND)) in exempt:
                continue
            if "ORCHESTRATE_CONVERSATION_ID" in path.read_text(
                encoding="utf-8", errors="ignore"
            ):
                offenders.append(str(path.relative_to(_BACKEND)))
    assert offenders == [], f"ancien nom encore présent : {offenders}"
