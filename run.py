from meeting_reminder.main import ReminderApp
from meeting_reminder.server import run_server

if __name__ == "__main__":
    run_server(ReminderApp())
