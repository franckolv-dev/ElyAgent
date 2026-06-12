# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_pii_cycle.py
# @brief      Cycle PII des missions (chantier 2026-06-12) — le dernier trou
#             documenté de la frontière souveraineté.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du cycle PII missions.

INVARIANT testé : la base et l'utilisateur vivent dans le monde réel ;
seul le LLM vit dans le monde des placeholders. Deux étages :

1. Unités du module ``app/agent/missions/pii.py``.
2. Gardes de câblage source-level (même pattern que test_learning_signals) :
   un refactor qui retire une couture anonymize/deanonymize des nodes,
   du dispatch, du critic ou des notifications DOIT casser la suite.

Run with:  cd backend && python -m pytest tests/test_mission_pii_cycle.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.missions.pii import anonymize_messages, deanonymize_any, mission_filter

_BACKEND = Path(__file__).resolve().parents[1]


# ── Unités ────────────────────────────────────────────────────────────────────

class TestMissionFilter:
    def test_same_instance_per_mission(self):
        sf1 = mission_filter("m-123")
        sf2 = mission_filter("m-123")
        assert sf1 is sf2

    def test_distinct_missions_distinct_vaults(self):
        assert mission_filter("m-aaa") is not mission_filter("m-bbb")

    def test_namespaced_key_never_collides_with_conversations(self):
        """Une mission dont l'id serait égal à un conversation_id ne doit
        JAMAIS partager son vault avec la conversation homonyme."""
        from app.services.conversation_filters import get_filter
        assert mission_filter("conv-42") is not get_filter("conv-42")


class TestAnonymizeMessages:
    def test_masks_pii_and_preserves_types(self):
        sf = mission_filter("m-anon-1")
        msgs = [
            SystemMessage(content="Plan : contacter le prospect."),
            HumanMessage(content="Goal : envoyer le devis à alice@acme.fr (06 12 34 56 78)"),
        ]
        out = anonymize_messages(sf, msgs)
        assert isinstance(out[0], SystemMessage) and isinstance(out[1], HumanMessage)
        assert "alice@acme.fr" not in out[1].content
        assert "[EMAIL_" in out[1].content and "[PHONE_" in out[1].content

    def test_originals_never_mutated(self):
        """Le monde réel (state, logs, fallback) garde les vraies valeurs."""
        sf = mission_filter("m-anon-2")
        original = HumanMessage(content="mail : bob@test.fr")
        anonymize_messages(sf, [original])
        assert original.content == "mail : bob@test.fr"

    def test_round_trip_through_llm_world(self):
        sf = mission_filter("m-anon-3")
        msgs = anonymize_messages(sf, [HumanMessage(content="Appelle le 06 11 22 33 44")])
        # le LLM répond en réutilisant le placeholder qu'il a vu
        placeholder = next(
            tok for tok in msgs[0].content.split() if tok.startswith("[PHONE_")
        )
        llm_output = f"J'ai programmé l'appel au {placeholder}"
        assert deanonymize_any(sf, llm_output) == "J'ai programmé l'appel au 06 11 22 33 44"


class TestDeanonymizeAny:
    def test_recursive_structures(self):
        sf = mission_filter("m-deanon-1")
        sf._vault["[EMAIL_0]"] = "carol@corp.fr"
        args = {"to": "[EMAIL_0]", "cc": ["[EMAIL_0]"], "meta": {"note": "envoyer à [EMAIL_0]"}, "n": 3}
        out = deanonymize_any(sf, args)
        assert out == {"to": "carol@corp.fr", "cc": ["carol@corp.fr"],
                       "meta": {"note": "envoyer à carol@corp.fr"}, "n": 3}

    def test_non_str_passthrough(self):
        sf = mission_filter("m-deanon-2")
        assert deanonymize_any(sf, 42) == 42
        assert deanonymize_any(sf, None) is None


# ── Gardes de câblage source-level ────────────────────────────────────────────

def _src(rel: str) -> str:
    return (_BACKEND / rel).read_text(encoding="utf-8")


class TestWiring:
    def test_nodes_anonymize_every_llm_call(self):
        """plan / act / eval / replan : chaque ainvoke de mission passe par
        anonymize_messages — 4 coutures minimum dans nodes.py."""
        src = _src("app/agent/missions/nodes.py")
        assert src.count("anonymize_messages(") >= 4, (
            "une couture anonymize_messages a disparu de missions/nodes.py"
        )

    def test_nodes_deanonymize_llm_output(self):
        """plan / eval / replan dé-anonymisent `raw` avant parse ; act
        dé-anonymise le content EDGE_CASE."""
        src = _src("app/agent/missions/nodes.py")
        assert src.count("deanonymize_any(") >= 4

    def test_dispatch_tool_deanonymizes_args(self):
        src = _src("app/agent/missions/nodes.py")
        dispatch = src.split("async def dispatch_tool(")[1].split("async def ")[0]
        assert "deanonymize_any(mission_filter(mission_id), tool_args)" in dispatch, (
            "dispatch_tool n'a plus la dé-anonymisation des args LLM"
        )

    def test_critic_anonymizes_audit_trail(self):
        src = _src("app/services/learning/mission_critic.py")
        assert "anonymize(prompt_text" in src and "deanonymize(raw)" in src, (
            "le mission critic (tier cloud) n'anonymise plus l'audit trail"
        )

    def test_heartbeat_notification_deanonymizes(self):
        src = _src("app/services/mission_heartbeat.py")
        assert "deanonymize(summary" in src

    def test_ask_user_notification_deanonymizes(self):
        src = _src("app/services/mission_spec_runtime.py")
        assert "deanonymize(question" in src


# ── Intégration : le cycle complet sur un faux LLM ───────────────────────────

class TestEndToEndCycle:
    @pytest.mark.asyncio
    async def test_pii_never_reaches_llm_and_args_come_back_real(self):
        """Le scénario prospection de Franck : goal avec email/téléphone →
        le « LLM » ne voit que des placeholders ; l'arg d'outil qu'il émet
        avec un placeholder ressort en vraie valeur."""
        sf = mission_filter("m-e2e-1")
        goal = "Envoie le devis à jean.dupont@acme.fr et appelle le 06 12 34 56 78"
        msgs = anonymize_messages(sf, [HumanMessage(content=f"Goal : {goal}")])

        seen_by_llm = msgs[0].content
        assert "jean.dupont@acme.fr" not in seen_by_llm
        assert "06 12 34 56 78" not in seen_by_llm

        # le LLM émet un tool_call avec les placeholders qu'il a vus
        placeholder_email = next(
            tok for tok in seen_by_llm.split() if tok.startswith("[EMAIL_")
        )
        fake_tool_args = {"to": placeholder_email, "subject": "Devis"}
        real_args = deanonymize_any(sf, fake_tool_args)
        assert real_args["to"] == "jean.dupont@acme.fr"
