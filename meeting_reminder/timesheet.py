import json
import os
from datetime import date, timedelta

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBMITTED_PATH = os.path.join(ROOT_DIR, "timesheet_state.json")

# Friday=4, Saturday=5 (Monday=0 ... Sunday=6)
HOLIDAY_WEEKDAYS = {4, 5}

ALERT_START_HOUR = 8
ALERT_END_HOUR = 16  # inclusive — fires at 8,9,...,16


def is_working_day(d):
    return d.weekday() not in HOLIDAY_WEEKDAYS


def _last_working_day_on_or_before(d):
    while not is_working_day(d):
        d -= timedelta(days=1)
    return d


def _add_months(year, month, offset):
    total = (year * 12 + (month - 1)) + offset
    return total // 12, total % 12 + 1


def _last_day_of_month(year, month):
    next_year, next_month = _add_months(year, month, 1)
    return date(next_year, next_month, 1) - timedelta(days=1)


def mid_month_deadline(year, month):
    return _last_working_day_on_or_before(date(year, month, 15))


def end_month_deadline(year, month):
    return _last_working_day_on_or_before(_last_day_of_month(year, month))


def deadline_period_label(d):
    return "mid-month" if d == mid_month_deadline(d.year, d.month) else "end-of-month"


def _candidate_deadlines(start_date, months_ahead=3):
    deadlines = []
    for offset in range(months_ahead):
        y, m = _add_months(start_date.year, start_date.month, offset)
        deadlines.append(mid_month_deadline(y, m))
        deadlines.append(end_month_deadline(y, m))
    return sorted(set(deadlines))


def _load_submitted():
    if not os.path.exists(SUBMITTED_PATH):
        return set()
    with open(SUBMITTED_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _save_submitted(submitted):
    with open(SUBMITTED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(submitted), f)


def get_next_deadline(today=None):
    """Earliest not-yet-submitted deadline — may be today, overdue, or future."""
    today = today or date.today()
    submitted = _load_submitted()
    for d in _candidate_deadlines(today):
        if d.isoformat() not in submitted:
            return d
    return None


def get_relevant_deadline(today=None):
    """Returns (deadline, is_submitted) for the deadline the UI should display.

    An overdue, unsubmitted deadline keeps being reported until it's marked
    submitted. A deadline that lands today keeps being reported as
    "submitted" for the rest of that day, so marking it doesn't instantly
    jump the panel to a date months away — it only rolls over once that day
    has passed.
    """
    today = today or date.today()
    submitted = _load_submitted()
    for d in _candidate_deadlines(today):
        if d >= today:
            return d, d.isoformat() in submitted
        if d.isoformat() not in submitted:
            return d, False
    return None, False


def mark_submitted(d):
    submitted = _load_submitted()
    submitted.add(d.isoformat())
    _save_submitted(submitted)
