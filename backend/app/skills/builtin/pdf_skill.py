"""PDF reading skill."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.pdf_tool import pdf_read, pdf_info

get_skill_registry().register(Skill(
    name="pdf",
    display_name="Lecture PDF",
    description="Lire, extraire le texte et les métadonnées de fichiers PDF (chemin local ou URL)",
    icon="📄",
    scopes=[],
    tools=[pdf_read, pdf_info],
))
