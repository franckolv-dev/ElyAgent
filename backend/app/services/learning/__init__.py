# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/__init__.py
# @brief      Sprint 3.7 — auto-improvement subpackage.
# @license    Elastic License 2.0
# @version    1.5.0
# =============================================================================
"""Learning subpackage — Sprint 3.7.

Self-improvement signals + LLM-as-judge critic + A/B testing scaffolding.
Jalon 3 (this file lands first) ships only the prompt_version helper.
Jalons 2, 4, 5 will populate this subpackage with more modules.
"""
from app.services.learning.ab_testing import (
    ab_score,
    register_variant,
    score_variants,
    select_variant,
)
from app.services.learning.mission_critic import (
    critique_mission,
    run_pending_critiques,
    should_critique,
)
from app.services.learning.prompt_version import (
    current_system_prompt_version,
    prompt_hash,
)
from app.services.learning.facade_detection import (
    compute_facade_signals,
    detect_claimed_no_tool,
    detect_write_intent,
    is_write_tool,
)
from app.services.learning.outcome_recording import (
    record_mission_outcome,
    record_scheduled_outcome,
)
from app.services.learning.signals import (
    classify_outcome,
    record_execution_outcome,
    record_hallucination_block,
    record_hitl_refusal,
    record_provider_switch,
    record_tool_error,
)
from app.services.learning.user_state import (
    DEFAULT_STATE,
    compute_user_state,
    format_user_state_block,
    get_user_state,
    set_user_state,
)

__all__ = [
    "prompt_hash",
    "current_system_prompt_version",
    "record_hitl_refusal",
    "record_hallucination_block",
    "record_tool_error",
    "record_provider_switch",
    "record_execution_outcome",
    "classify_outcome",
    "compute_facade_signals",
    "detect_write_intent",
    "detect_claimed_no_tool",
    "is_write_tool",
    "record_scheduled_outcome",
    "record_mission_outcome",
    "should_critique",
    "critique_mission",
    "run_pending_critiques",
    "select_variant",
    "register_variant",
    "ab_score",
    "score_variants",
    "DEFAULT_STATE",
    "get_user_state",
    "set_user_state",
    "compute_user_state",
    "format_user_state_block",
]
