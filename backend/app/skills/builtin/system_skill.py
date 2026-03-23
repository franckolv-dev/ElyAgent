from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.ssh_tool import ssh_execute
from app.agent.tools.file_tool import analyze_file
from app.agent.tools.system_tool import system_info

get_skill_registry().register(Skill(
    name="system",
    display_name="Système & SSH",
    description="Exécuter des commandes SSH sur des serveurs distants, analyser des fichiers, obtenir des infos système",
    icon="🖥️",
    scopes=["ssh"],
    tools=[ssh_execute, analyze_file, system_info],
))
