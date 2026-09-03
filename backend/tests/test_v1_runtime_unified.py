# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_v1_runtime_unified.py
# @brief      V1 temps 2 — un seul runtime d'agent, plus deux.
# @license    MIT
# =============================================================================
"""Pins du runtime unifié (vague 1, temps 2 — destructif).

**La décision, prise sur mesure.** Le banc A/B (#248) a comparé les deux
architectures sur 20 demandes réellement formulées :

    tier B   latence p50   1 657 ms (mono)  contre  2 713 ms (sous-agents)
             choix d outil      85 %                     78 %
    tier A   latence p50   3 431 ms         contre 13 082 ms
             choix d outil     100 %                     62 %

La règle posée à l'avance par Franck — « si le mono-agent ne dégrade pas la
latence ET fait aussi bien ou mieux, on unifie » — était remplie sur les deux
conditions. Et la prémisse d'origine s'est révélée **inversée** : le
superviseur avait été introduit pour soulager le tier A local, c'est là qu'il
coûtait le plus cher, parce que l'appel de routage tourne lui aussi sur le
modèle local.

**Ce que le temps 1 (#249) avait déjà fait** : toutes les surfaces passent un
``toolset_profile``, ce qui court-circuite le routeur. Les 8 branches de
dispatch étaient donc enregistrées mais **jamais entrées**.

**Ce que ce lot fait** : ``build_agent_graph()`` construit directement le
graphe plat, et ``supervisor.py`` + ``sub_agents/`` disparaissent
(~2 800 lignes).

**Vérifié avant de supprimer** : ``state["domain"]``, seule information que le
routeur produisait, n'est lu par personne en dehors de ``supervisor.py``. Et
les deux graphes étaient structurellement identiques une fois le routage
retiré — ``general`` ≡ ``agent``, mêmes arêtes vers ``tools`` et
``force_summary``.

Run with:  cd backend && python -m pytest tests/test_v1_runtime_unified.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ------------------------------------------------- ce qui disparaît

def test_the_supervisor_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        import app.agent.supervisor  # noqa: F401


def test_the_sub_agents_package_is_gone():
    with pytest.raises(ModuleNotFoundError):
        import app.agent.sub_agents  # noqa: F401


def test_no_production_code_imports_them_any_more():
    """Un import résiduel ferait planter le démarrage — c'est exactement la
    classe d'erreur qu'un pin source-grep laisse passer et qu'un import
    attrape."""
    offenders: list[str] = []
    for path in Path("app").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        for line in src.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue
            if "agent.supervisor" in stripped or "agent.sub_agents" in stripped:
                offenders.append(f"{path}: {stripped}")

    assert not offenders, "imports résiduels :\n" + "\n".join(offenders)


# ------------------------------------------- ce qui continue de marcher

def test_the_production_graph_still_builds():
    """Non-régression : les 7 surfaces appellent toutes `build_agent_graph`."""
    from app.agent.graph import build_agent_graph

    assert build_agent_graph() is not None


def test_the_production_graph_is_the_flat_one():
    """Plus de routeur, plus de dispatch — un seul nœud agent."""
    from app.agent.graph import build_agent_graph

    nodes = set(build_agent_graph().get_graph().nodes)

    assert "agent" in nodes
    assert "tools" in nodes
    assert "force_summary" in nodes
    assert "router" not in nodes, "le routeur est encore dans le graphe"
    for domain in ("research", "workspace", "infra", "creative", "data",
                   "memory", "desktop", "diag"):
        assert domain not in nodes, f"le nœud de dispatch '{domain}' subsiste"


def test_both_builders_now_describe_the_same_graph():
    """`build_agent_graph` et `build_simple_agent_graph` ne divergent plus :
    c'était toute la « matrice de divergence » que l'audit reprochait."""
    from app.agent.graph import build_agent_graph, build_simple_agent_graph

    assert set(build_agent_graph().get_graph().nodes) == set(
        build_simple_agent_graph().get_graph().nodes
    )


def test_the_startup_no_longer_registers_sub_agents():
    """`main.py` compilait 8 sous-graphes au démarrage — du temps de boot
    pour des branches jamais entrées."""
    src = Path("app/main.py").read_text(encoding="utf-8")

    assert "get_sub_agent_registry" not in src
    assert "Sub-agent registry ready" not in src


def test_delegate_survives():
    """`delegate` est un OUTIL, pas une architecture : l'audit demandait
    explicitement de le garder."""
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()

    assert "delegate" in {t.name for t in get_skill_registry().all_tools}


# ------------------------------- le contrat PII reste couvert ailleurs

def test_the_pii_contract_is_still_pinned_on_the_central_gateway():
    """Les tests PII supprimés visaient des MIROIRS dans la factory. Le
    contrat réel vit dans la passerelle — il doit rester verrouillé, sinon
    supprimer les miroirs ferait perdre la couverture."""
    src = Path("tests/test_tool_gateway.py").read_text(encoding="utf-8")

    assert "test_gateway_pii_round_trip" in src
