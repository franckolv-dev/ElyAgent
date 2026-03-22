from app.agent.tools.ssh_tool import ssh_execute
from app.agent.tools.file_tool import analyze_file
from app.agent.tools.system_tool import system_info
from app.agent.tools.gmail_tool import gmail_list_emails, gmail_read_email, gmail_send_email
from app.agent.tools.calendar_tool import calendar_list_events, calendar_create_event
from app.agent.tools.drive_tool import drive_list_files, drive_read_file

all_tools = [
    ssh_execute,
    analyze_file,
    system_info,
    gmail_list_emails,
    gmail_read_email,
    gmail_send_email,
    calendar_list_events,
    calendar_create_event,
    drive_list_files,
    drive_read_file,
]
