from app.agent.tools.ssh_tool import ssh_execute
from app.agent.tools.file_tool import analyze_file
from app.agent.tools.system_tool import system_info
from app.agent.tools.gmail_tool import gmail_list_emails, gmail_read_email, gmail_send_email
from app.agent.tools.calendar_tool import calendar_list_events, calendar_create_event
from app.agent.tools.drive_tool import drive_list_files, drive_read_file
from app.agent.tools.docs_tool import docs_create_document, docs_read_document, docs_append_text
from app.agent.tools.sheets_tool import sheets_create_spreadsheet, sheets_read_spreadsheet, sheets_append_rows
from app.agent.tools.tasks_tool import tasks_list, tasks_create, tasks_complete
from app.agent.tools.scheduler_tool import scheduler_list_tasks, scheduler_create_task, scheduler_delete_task

all_tools = [
    ssh_execute,
    analyze_file,
    system_info,
    # Gmail
    gmail_list_emails,
    gmail_read_email,
    gmail_send_email,
    # Calendar
    calendar_list_events,
    calendar_create_event,
    # Drive
    drive_list_files,
    drive_read_file,
    # Google Docs (≈ Word)
    docs_create_document,
    docs_read_document,
    docs_append_text,
    # Google Sheets (≈ Excel)
    sheets_create_spreadsheet,
    sheets_read_spreadsheet,
    sheets_append_rows,
    # Google Tasks
    tasks_list,
    tasks_create,
    tasks_complete,
    # Scheduler (cron tasks)
    scheduler_list_tasks,
    scheduler_create_task,
    scheduler_delete_task,
]
