from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.sheets_tool import sheets_create_spreadsheet, sheets_read_spreadsheet, sheets_append_rows

get_skill_registry().register(Skill(
    name="google_sheets",
    display_name="Google Sheets",
    description="Créer, lire et modifier des feuilles de calcul Google Sheets (équivalent Excel)",
    icon="📊",
    scopes=["google_oauth"],
    tools=[sheets_create_spreadsheet, sheets_read_spreadsheet, sheets_append_rows],
))
