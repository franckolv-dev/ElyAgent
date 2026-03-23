from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.drive_tool import drive_list_files, drive_read_file

get_skill_registry().register(Skill(
    name="google_drive",
    display_name="Google Drive",
    description="Lister et lire des fichiers sur Google Drive",
    icon="📁",
    scopes=["google_oauth"],
    tools=[drive_list_files, drive_read_file],
))
