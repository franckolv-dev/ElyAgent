# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/telegram_skill.py
# @brief      Telegram outbound skill — push messages to the calling user.
# =============================================================================
"""Telegram outbound skill — registers `telegram_send_message`.

Enables missions and scheduled tasks to push their results to the user's
own Telegram chat (one recipient only — security via InjectedToolArg).
"""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.telegram_tool import telegram_send_message

get_skill_registry().register(Skill(
    name="telegram",
    display_name="Telegram",
    description=(
        "Push des messages Telegram à l'utilisateur courant (compte lié via /link). "
        "Idéal pour briefings quotidiens, alertes de mission, résumés de tâches "
        "planifiées. UN SEUL destinataire : l'utilisateur lui-même."
    ),
    icon="✈️",
    scopes=["telegram"],
    domains=[Domain.MEMORY],
    tools=[
        telegram_send_message,
    ],
))
