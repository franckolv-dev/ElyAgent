# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/__init__.py
# @brief      Package init for models
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.models.audit import AuditLog
from app.models.revoked_token import RevokedToken
from app.models.mission import Mission, MissionPlan, MissionStep
from app.models.google_account import GoogleAccount
from app.models.watched_folder import WatchedFolder
from app.models.hitl_preference import HitlPreference
from app.models.user_vocabulary import UserVocabulary
from app.models.learned_routing_keyword import LearnedRoutingKeyword
from app.models.licence import Licence
from app.models.extension_token import ExtensionToken
from app.models.procedure import Procedure
from app.models.error_log import ErrorLog
from app.models.hitl_refusal import HitlRefusal
from app.models.hallucination_block import HallucinationBlock
from app.models.provider_switch import ProviderSwitch
from app.models.mission_critique import MissionCritique
from app.models.user_state import UserState
# Models that were registered with Base.metadata only by side-effect of being
# imported from other parts of the codebase. Listing them here makes the
# dependency explicit so ``Base.metadata.create_all`` sees their tables on a
# fresh DB (notably in CI's in-memory sqlite, where nothing else imports
# them before tests run).
from app.models.arena import ArenaMatch, ArenaElo
from app.models.community_skill import CommunitySkill
from app.models.feedback import Feedback
from app.models.llm_instance import LLMInstance
from app.models.mcp_server import MCPServer
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
    "HitlPreference", "UserVocabulary", "LearnedRoutingKeyword",
    "Licence", "ExtensionToken",
    "Procedure", "ErrorLog",
    "HitlRefusal", "HallucinationBlock", "ProviderSwitch", "MissionCritique",
    "UserState",
    # Newly explicit (side-effect imports promoted to first-class)
    "ArenaMatch", "ArenaElo", "CommunitySkill", "Feedback", "LLMInstance",
    "MCPServer", "Note", "ScheduledTask", "SkillPreference", "SystemConfig",
    "UsageLog", "UserMemoryLog", "UserProfile", "VaultConfig", "VaultEntry",
    "WatchTask",
]
