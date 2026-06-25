import calendar
import json
import os
from datetime import date

from . import holidays_eg
from .timesheet import is_working_day

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKED_DAYS_PATH = os.path.join(ROOT_DIR, "worked_days_state.json")


def _load_worked():
    if not os.path.exists(WORKED_DAYS_PATH):
        return set()
    with open(WORKED_DAYS_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _save_worked(worked):
    with open(WORKED_DAYS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(worked), f)


def set_worked(d, is_worked):
    worked = _load_worked()
    key = d.isoformat()
    if is_worked:
        worked.add(key)
    else:
        worked.discard(key)
    _save_worked(worked)


def first_half_days(year, month):
    return [date(year, month, day) for day in range(1, 16)]


def second_half_days(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return [date(year, month, day) for day in range(16, last_day + 1)]


def current_period_days(today=None):
    """The days + range label for whichever half of the month contains `today`."""
    today = today or date.today()
    if today.day <= 15:
        return first_half_days(today.year, today.month), "1–15"
    last_day = calendar.monthrange(today.year, today.month)[1]
    return second_half_days(today.year, today.month), f"16–{last_day}"


def period_summary(days, hours_per_day):
    """Filters to working weekdays only. Nothing counts as worked by default —
    a day must be explicitly marked (clicked) to add a day/hours to the worked
    total; every other non-holiday working weekday counts as "remaining".
    """
    worked = _load_worked()
    entries = []
    worked_days = 0
    remaining_days = 0
    holiday_count = 0
    for d in days:
        if not is_working_day(d):
            continue
        holiday = holidays_eg.holiday_name(d)
        is_worked = d.isoformat() in worked
        if holiday is not None:
            holiday_count += 1
        elif is_worked:
            worked_days += 1
        else:
            remaining_days += 1
        entries.append({"date": d, "holidayName": holiday, "isWorked": is_worked})
    return {
        "days": entries,
        "workedDays": worked_days,
        "remainingDays": remaining_days,
        "holidayCount": holiday_count,
        "workedHours": worked_days * hours_per_day,
        "remainingHours": remaining_days * hours_per_day,
    }
