# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/__init__.py
# @brief      Sprint 3.7 — auto-improvement subpackage.
# @license    PolyForm Strict License 1.0.0
# @version    1.5.0
# =============================================================================
"""Learning subpackage — Sprint 3.7.

Self-improvement signals + LLM-as-judge critic + A/B testing scaffolding.
Jalon 3 (this file lands first) ships only the prompt_version helper.
Jalons 2, 4, 5 will populate this subpackage with more modules.
"""
from app.services.learning.prompt_version import (
    current_system_prompt_version,
    prompt_hash,
)

__all__ = [
    "prompt_hash",
    "current_system_prompt_version",
]
