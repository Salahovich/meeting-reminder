import json
import os
from datetime import date, timedelta

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKED_PATH = os.path.join(ROOT_DIR, "office_days_state.json")

# Python's date.weekday(): Monday=0 ... Sunday=6. The tracked work week is
# Sunday-Thursday (Friday/Saturday are holidays, matching timesheet.py).
WORK_WEEKDAYS = {6, 0, 1, 2, 3}
DAY_LABELS = {6: "SUN", 0: "MON", 1: "TUE", 2: "WED", 3: "THU"}

MORNING_ALERT_HOUR = 7
EVENING_ALERT_HOUR = 20


def is_office_weekday(d):
    return d.weekday() in WORK_WEEKDAYS


def week_days(today=None):
    """The 5 dates (Sun..Thu) of the week containing `today`."""
    today = today or date.today()
    sunday_offset = (today.weekday() + 1) % 7  # Sunday=0 ... Saturday=6
    sunday = today - timedelta(days=sunday_offset)
    return [sunday + timedelta(days=i) for i in range(5)]


def _load_marked():
    if not os.path.exists(MARKED_PATH):
        return set()
    with open(MARKED_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _save_marked(marked):
    with open(MARKED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(marked), f)


def mark(d):
    marked = _load_marked()
    marked.add(d.isoformat())
    _save_marked(marked)


def unmark(d):
    marked = _load_marked()
    marked.discard(d.isoformat())
    _save_marked(marked)


def toggle_marked(d):
    marked = _load_marked()
    key = d.isoformat()
    if key in marked:
        marked.discard(key)
    else:
        marked.add(key)
    _save_marked(marked)


def get_week_status(minimum, today=None):
    days = week_days(today)
    marked = _load_marked()
    count = sum(1 for d in days if d.isoformat() in marked)
    return {
        "days": days,
        "markedSet": marked,
        "count": count,
        "minimum": minimum,
        "met": count >= minimum,
    }


def shortfall_today(minimum, today=None):
    """True if today still needs an office visit to help reach the weekly minimum."""
    today = today or date.today()
    if not is_office_weekday(today):
        return False
    marked = _load_marked()
    if today.isoformat() in marked:
        return False
    days = week_days(today)
    count = sum(1 for d in days if d.isoformat() in marked)
    return count < minimum


def shortfall_tomorrow_evening(minimum, today=None):
    """True if tomorrow (still within this same work week) needs an office visit."""
    today = today or date.today()
    if not is_office_weekday(today):
        return False
    days = week_days(today)
    if today == days[-1]:  # Thursday has no "tomorrow" within this work week
        return False
    marked = _load_marked()
    count = sum(1 for d in days if d.isoformat() in marked)
    return count < minimum
