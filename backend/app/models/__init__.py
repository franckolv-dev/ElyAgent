# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/__init__.py
# @brief      Package init for models
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.models.audit import AuditLog
from app.models.revoked_token import RevokedToken
from app.models.mission import Mission, MissionPlan, MissionStep
from app.models.google_account import GoogleAccount
from app.models.watched_folder import WatchedFolder
from app.models.hitl_preference import HitlPreference
from app.models.hitl_request import HitlRequest
from app.models.user_vocabulary import UserVocabulary
from app.models.licence import Licence
from app.models.extension_token import ExtensionToken
from app.models.api_key import ApiKey
from app.models.procedure import Procedure
from app.models.error_log import ErrorLog
from app.models.hitl_refusal import HitlRefusal
from app.models.hallucination_block import HallucinationBlock
from app.models.provider_switch import ProviderSwitch
from app.models.mission_critique import MissionCritique
# Boucle d'auto-diagnostic J1 — verdict d'aboutissement réel par exécution.
from app.models.execution_outcome import ExecutionOutcome
# Boucle d'auto-diagnostic J3 — hypothèse de cause + catégorie (maillon 2).
from app.models.execution_diagnosis import ExecutionDiagnosis
# Boucle d'auto-diagnostic J5 — correctif config/prompt validable (voie C).
from app.models.proposed_patch import ProposedPatch
from app.models.user_state import UserState
# Sprint 4b Phase 1 — auto-amélioration par création de skills (Hermes-style)
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill, SkillStatus, SkillSource
from app.models.anticipation import AnticipationSuggestion, SuggestionStatus
# Sprint 4b V3 J6.c.1 — per-call audit for io python_tool dispatches.
from app.models.io_tool_dispatch import IoToolDispatch
# Models that were registered with Base.metadata only by side-effect of being
# imported from other parts of the codebase. Listing them here makes the
# dependency explicit so ``Base.metadata.create_all`` sees their tables on a
# fresh DB (notably in CI's in-memory sqlite, where nothing else imports
# them before tests run).
from app.models.community_skill import CommunitySkill
from app.models.feedback import Feedback
from app.models.llm_instance import LLMInstance
from app.models.mcp_server import MCPServer, MCPTool, MCPToolPermission
from app.models.idempotency import IdempotencyRecord
from app.models.reversible_action import ReversibleActionRecord
from app.models.note import Note
from app.models.scheduled_task import ScheduledTask
from app.models.skill_preference import SkillPreference
from app.models.system_config import SystemConfig
from app.models.usage_log import UsageLog
from app.models.user_memory import UserMemoryLog, UserProfile
from app.models.vault import VaultConfig, VaultEntry
from app.models.watch_task import WatchTask

__all__ = [
    "User", "Conversation", "Message", "AuditLog", "RevokedToken",
    "Mission", "MissionPlan", "MissionStep", "GoogleAccount", "WatchedFolder",
    "HitlPreference", "UserVocabulary",
    "Licence", "ExtensionToken", "ApiKey",
    "Procedure", "ErrorLog",
    "HitlRefusal", "HallucinationBlock", "ProviderSwitch", "MissionCritique",
    "ExecutionOutcome", "ExecutionDiagnosis", "ProposedPatch",
    "UserState",
    "FailureCase", "LearnedSkill", "SkillStatus", "SkillSource",
    "IoToolDispatch",
    # Newly explicit (side-effect imports promoted to first-class)
    "CommunitySkill", "Feedback", "LLMInstance",
    "MCPServer", "MCPTool", "MCPToolPermission", "IdempotencyRecord",
    "Note", "ScheduledTask", "SkillPreference", "SystemConfig",
    "UsageLog", "UserMemoryLog", "UserProfile", "VaultConfig", "VaultEntry",
    "WatchTask",
    # C5 — anticipation (mode suggestion)
    "AnticipationSuggestion", "SuggestionStatus",
]
