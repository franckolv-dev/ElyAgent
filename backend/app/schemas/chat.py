# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/schemas/chat.py
# @brief      Chat WebSocket and REST endpoints
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from pydantic import BaseModel
from datetime import datetime


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    role: str
    content: str
    conversation_id: str
    message_id: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
