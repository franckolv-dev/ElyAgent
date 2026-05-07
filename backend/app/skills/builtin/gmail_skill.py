# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/gmail_skill.py
# @brief      Gmail Skill module
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
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.gmail_tool import (
    gmail_list_emails,
    gmail_read_email,
    gmail_send_email,
    gmail_list_labels,
    gmail_create_label,
    gmail_move_emails,
    gmail_trash_emails,
    gmail_search_for_cleanup,
    gmail_trash_by_category,
    gmail_trash_by_query,
    gmail_reply_email,
    gmail_send_with_attachment,
    gmail_send_with_local_attachment,
    gmail_mark_read,
    gmail_mark_unread,
    gmail_create_draft,
    gmail_list_drafts,
    gmail_batch_modify,
    gmail_update_settings,
    gmail_raw_api_call,
)

get_skill_registry().register(Skill(
    name="google_gmail",
    display_name="Gmail",
    description=(
        "Lire, chercher, envoyer, répondre et organiser des emails via Gmail. "
        "Modif en lot jusqu'à 1000 mails, paramètres (signature, absence, "
        "filtres, transfert), plus accès complet via gmail_raw_api_call."
    ),
    icon="✉️",
    scopes=["google_oauth"],
    domains=[Domain.WORKSPACE],
    tools=[
        gmail_list_emails,
        gmail_read_email,
        gmail_send_email,
        gmail_reply_email,
        gmail_send_with_attachment,
        gmail_send_with_local_attachment,
        gmail_mark_read,
        gmail_mark_unread,
        gmail_create_draft,
        gmail_list_drafts,
        gmail_list_labels,
        gmail_create_label,
        gmail_move_emails,
        gmail_trash_emails,
        gmail_search_for_cleanup,
        gmail_trash_by_category,
        gmail_trash_by_query,
        gmail_batch_modify,
        gmail_update_settings,
        gmail_raw_api_call,
    ],
))
