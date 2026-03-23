from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.docs_tool import docs_create_document, docs_read_document, docs_append_text

get_skill_registry().register(Skill(
    name="google_docs",
    display_name="Google Docs",
    description="Créer, lire et modifier des documents Google Docs (équivalent Word)",
    icon="📝",
    scopes=["google_oauth"],
    tools=[docs_create_document, docs_read_document, docs_append_text],
))
