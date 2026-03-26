"""Python sandbox skill."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.python_tool import python_execute

get_skill_registry().register(Skill(
    name="python-sandbox",
    display_name="Python Sandbox",
    description="Exécute du code Python pour calculs, analyses de données et scripts",
    icon="🐍",
    scopes=[],
    tools=[python_execute],
))
