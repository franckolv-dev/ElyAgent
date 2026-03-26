"""Notes / Presse-papier skill — create and manage personal notes."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.notes_tool import (
    notes_create,
    notes_list,
    notes_read,
    notes_update,
    notes_delete,
    notes_search,
)

get_skill_registry().register(Skill(
    name="notes",
    display_name="Notes & Presse-papier",
    description=(
        "Crée, consulte, modifie et supprime des notes personnelles / presse-papier. "
        "Supporte titres, contenu, tags et épingles."
    ),
    icon="📝",
    scopes=[],
    tools=[
        notes_create,
        notes_list,
        notes_read,
        notes_update,
        notes_delete,
        notes_search,
    ],
))
