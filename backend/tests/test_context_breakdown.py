# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_context_breakdown.py
# @brief      P2 — savoir enfin d'où viennent les tokens d'un tour.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de la ventilation du contexte (port de Hermes v0.19, MIT).

**Le besoin, mesuré.** Relevé sur la production le 25/07, tokens d'ENTRÉE
moyens par tour sur 7 jours :

    desktop_search_files ... 230 203
    browser_navigate ....... 175 232
    pdf_read ............... 141 867
    find_tool ...............  80 041  (× 14 = 1,12 M)

Impossible de dire d'où ils viennent : schémas d'outils re-envoyés à chaque
itération ? historique de conversation ? un seul résultat d'outil énorme ?
Sans cette réponse, toute optimisation du contexte est un pari.

**Ce qui est porté.** `agent/context_breakdown.py` de Hermes v0.19 : une
décomposition par catégories de ce que pèse la prochaine requête. Le principe
retenu, et il compte : **la ventilation utilise l'estimateur qui pilote déjà
les troncatures** — chez Hermes `chars/4` (leur seuil de compression), chez
Ely ``context_manager.estimate_tokens`` (`chars/3.5`). Porter la constante
plutôt que le principe donnerait des chiffres qui ne correspondraient à
aucune décision réelle du système.

**Catégories adaptées à Ely** : leurs `rules` et leur découpage MCP `mcp_`
n'existent pas tels quels ; Ely a le préfixe `mcp__` et l'outil `delegate`
(eux : `delegate_task`).

Run with:  cd backend && python -m pytest tests/test_context_breakdown.py -v
"""
from __future__ import annotations

import pytest


class _Tool:
    """Outil minimal : le nom suffit au classement, la description au poids."""

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description or f"description de {name}"


def _cats(result: dict) -> dict[str, int]:
    return {c["id"]: c["tokens"] for c in result["categories"]}


# --------------------------------------------------------- le classement

def test_native_mcp_and_delegate_tools_are_counted_apart():
    """L'intérêt du portage est là : savoir si le poids vient des outils
    natifs, des serveurs MCP tiers ou de la délégation."""
    from app.services.context_breakdown import compute_context_breakdown

    result = compute_context_breakdown(
        system_prompt="Tu es Ely.",
        tools=[
            _Tool("gmail_list_emails"),
            _Tool("mcp__weather__forecast"),
            _Tool("delegate"),
        ],
        messages=[],
    )

    cats = _cats(result)
    assert cats["tool_definitions"] > 0
    assert cats["mcp"] > 0
    assert cats["subagent_definitions"] > 0


def test_the_learned_skills_block_is_counted_apart_from_the_prompt():
    """Ely injecte ses playbooks dans `<learned_skills>`. Les compter avec le
    prompt masquerait leur coût réel — or c'est précisément ce qu'on veut
    pouvoir arbitrer."""
    from app.services.context_breakdown import compute_context_breakdown

    skills = "<learned_skills>\n" + ("- un playbook assez long\n" * 40) + "</learned_skills>"
    result = compute_context_breakdown(
        system_prompt=f"Tu es Ely.\n\n{skills}\n\nFin du prompt.",
        tools=[],
        messages=[],
    )

    cats = _cats(result)
    assert cats["skills"] > 0
    # Le bloc ne doit pas être compté DEUX fois.
    assert cats["system_prompt"] < cats["skills"]


def test_the_conversation_is_counted_apart():
    from app.services.context_breakdown import compute_context_breakdown

    result = compute_context_breakdown(
        system_prompt="Tu es Ely.",
        tools=[],
        messages=[{"role": "user", "content": "bonjour " * 500}],
    )

    assert _cats(result)["conversation"] > 100


def test_a_huge_tool_result_shows_up_in_the_conversation():
    """LE cas mesuré : 230 203 tokens sur un tour `desktop_search_files`. Un
    seul résultat d'outil énorme doit être visible, pas dilué."""
    from app.services.context_breakdown import compute_context_breakdown

    result = compute_context_breakdown(
        system_prompt="Tu es Ely.",
        tools=[_Tool("desktop_search_files")],
        messages=[
            {"role": "user", "content": "cherche mes fichiers"},
            {"role": "tool", "content": "x" * 400_000},
        ],
    )

    cats = _cats(result)
    assert cats["conversation"] > 100_000
    assert cats["conversation"] > cats["tool_definitions"] * 10


# ------------------------------------------- alignement avec l'estimateur

def test_the_breakdown_uses_the_same_estimator_as_the_truncation():
    """Le principe porté de Hermes : la ventilation doit parler la même
    langue que le mécanisme qui décide de tronquer. Sinon elle décrit un
    contexte que le système ne voit pas."""
    from app.services.context_breakdown import compute_context_breakdown
    from app.services.context_manager import estimate_tokens

    text = "une phrase de longueur quelconque " * 30
    result = compute_context_breakdown(system_prompt=text, tools=[], messages=[])

    assert _cats(result)["system_prompt"] == estimate_tokens(text)


def test_the_total_is_the_sum_of_the_categories():
    from app.services.context_breakdown import compute_context_breakdown

    result = compute_context_breakdown(
        system_prompt="Tu es Ely.",
        tools=[_Tool("a"), _Tool("mcp__x__y")],
        messages=[{"role": "user", "content": "salut"}],
    )

    assert result["estimated_total"] == sum(_cats(result).values())


# ------------------------------------------------------------ robustesse

def test_empty_categories_are_dropped():
    """Pas de bruit : une catégorie à zéro ne figure pas dans la sortie."""
    from app.services.context_breakdown import compute_context_breakdown

    result = compute_context_breakdown(system_prompt="Tu es Ely.", tools=[], messages=[])

    assert "mcp" not in _cats(result)
    assert "skills" not in _cats(result)


def test_it_never_raises_on_odd_input():
    """La ventilation est un instrument de mesure : elle ne doit jamais
    coûter un tour à l'utilisateur."""
    from app.services.context_breakdown import compute_context_breakdown

    for tools in ([], None, [object()]):
        for messages in ([], None, [None], "pas une liste"):
            out = compute_context_breakdown(
                system_prompt="x", tools=tools, messages=messages
            )
            assert isinstance(out["estimated_total"], int)


def test_the_compact_form_is_queryable():
    """Elle est destinée à `usage_logs` : une forme compacte, stable, et
    interrogeable en SQL sans parser du texte libre."""
    from app.services.context_breakdown import compact_breakdown, compute_context_breakdown

    result = compute_context_breakdown(
        system_prompt="Tu es Ely.",
        tools=[_Tool("a")],
        messages=[{"role": "user", "content": "salut"}],
    )
    compact = compact_breakdown(result)

    import json
    parsed = json.loads(compact)
    assert parsed["total"] == result["estimated_total"]
    assert parsed["system_prompt"] > 0
    assert len(compact) < 300, "la colonne doit rester légère"


def test_compact_form_of_an_empty_breakdown_is_none():
    """Rien à dire → rien en base, plutôt qu'un JSON vide qui pollue."""
    from app.services.context_breakdown import compact_breakdown

    assert compact_breakdown({}) is None
    assert compact_breakdown({"categories": [], "estimated_total": 0}) is None


# ------------------------------------------ le pourcentage de fenêtre

def test_the_window_percentage_is_reported_when_the_model_is_known():
    """Savoir qu'un tour pèse 230 k tokens ne dit rien sans la fenêtre du
    modèle. 230 k sur 1 M, ou sur 128 k, ce n'est pas la même urgence."""
    from app.services.context_breakdown import compute_context_breakdown

    result = compute_context_breakdown(
        system_prompt="x" * 40_000, tools=[], messages=[], model="gpt-5.6-terra",
    )

    assert result["context_max"] > 0
    assert 0 < result["context_percent"] <= 100


def test_no_percentage_without_a_model():
    from app.services.context_breakdown import compute_context_breakdown

    result = compute_context_breakdown(system_prompt="x", tools=[], messages=[])

    assert result["context_percent"] == 0


@pytest.mark.asyncio
async def test_the_breakdown_is_persisted_with_the_turn():
    """Le but du lot : pouvoir répondre à « ces 230 000 tokens venaient d'où ? »
    sur du trafic RÉEL, pas sur un banc. La ventilation doit donc arriver en
    base avec le reste de la consommation du tour."""
    import uuid

    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.usage_log import UsageLog
    from app.models.user import User
    from app.services.analytics_service import log_usage

    await init_db()
    uid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uuid.uuid4().hex[:8]}",
                    email=f"{uuid.uuid4().hex[:8]}@t.local", hashed_password="x"))
        await db.commit()

    await log_usage(
        user_id=uid, model="m", provider="p", input_tokens=230203, output_tokens=50,
        context_breakdown='{"tool_definitions":18173,"conversation":210000,"total":228173}',
    )

    async with async_session() as db:
        row = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == uid)
        )).scalar_one()

    import json
    parsed = json.loads(row.context_breakdown)
    assert parsed["conversation"] == 210000
    assert parsed["tool_definitions"] == 18173


@pytest.mark.asyncio
async def test_an_unmeasured_turn_stays_null():
    """Rétrocompatibilité : les appelants historiques laissent la colonne à
    NULL — « non ventilé », et non « ventilé à zéro »."""
    import uuid

    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.usage_log import UsageLog
    from app.models.user import User
    from app.services.analytics_service import log_usage

    await init_db()
    uid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uuid.uuid4().hex[:8]}",
                    email=f"{uuid.uuid4().hex[:8]}@t.local", hashed_password="x"))
        await db.commit()

    await log_usage(user_id=uid, model="m", provider="p", input_tokens=10, output_tokens=5)

    async with async_session() as db:
        row = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == uid)
        )).scalar_one()
    assert row.context_breakdown is None


def test_the_agent_node_computes_the_breakdown():
    """Pin : la ventilation doit être calculée là où la requête est complète
    — prompt assemblé, outils bindés, messages ajustés — sinon elle mesure
    autre chose que ce qui part au fournisseur."""
    from pathlib import Path

    src = Path("app/agent/nodes.py").read_text(encoding="utf-8")

    assert "compute_context_breakdown" in src
    assert src.index("_invoke_msgs = (") < src.index("compute_context_breakdown"), (
        "la ventilation est calculée avant l'assemblage final des messages"
    )
