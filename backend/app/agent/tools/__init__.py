from app.agent.tools.ssh_tool import ssh_execute
from app.agent.tools.file_tool import analyze_file
from app.agent.tools.system_tool import system_info

all_tools = [ssh_execute, analyze_file, system_info]
