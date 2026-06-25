"""Throwaway script to visually test the timesheet alert without touching real data.

Opens the normal widget, but fires a fake timesheet alert ~2 seconds after launch,
and redirects the submitted-state file to a scratch path so clicking "MARK AS
SUBMITTED" during the test can't mark the real upcoming deadline as done.

Run: ./.venv/Scripts/python.exe scratch_test_timesheet_alert.py
Delete this file when done testing.
"""
import threading
from datetime import date

from meeting_reminder import timesheet
from meeting_reminder.main import ReminderApp

# Redirect persistence so this test can't corrupt the real timesheet_state.json.
timesheet.SUBMITTED_PATH = "scratch_timesheet_state_test.json"


def fire_test_alert(app):
    app._fire_timesheet_alert(date.today())


def main():
    app = ReminderApp()
    threading.Timer(2.0, fire_test_alert, args=(app,)).start()
    app.run()


if __name__ == "__main__":
    main()
