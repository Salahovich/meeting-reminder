import calendar
import json
import os
from datetime import date

from . import holidays_eg
from .timesheet import is_working_day

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS_OFF_PATH = os.path.join(ROOT_DIR, "days_off_state.json")


def _load_days_off():
    if not os.path.exists(DAYS_OFF_PATH):
        return set()
    with open(DAYS_OFF_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _save_days_off(days_off):
    with open(DAYS_OFF_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(days_off), f)


def toggle_day_off(d):
    days_off = _load_days_off()
    key = d.isoformat()
    if key in days_off:
        days_off.discard(key)
    else:
        days_off.add(key)
    _save_days_off(days_off)


def first_half_days(year, month):
    return [date(year, month, day) for day in range(1, 16)]


def second_half_days(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return [date(year, month, day) for day in range(16, last_day + 1)]


def period_summary(days, hours_per_day):
    """Filters to working weekdays only, marking holidays/days-off, and totals hours."""
    days_off = _load_days_off()
    entries = []
    countable = 0
    for d in days:
        if not is_working_day(d):
            continue
        holiday = holidays_eg.holiday_name(d)
        is_off = d.isoformat() in days_off
        if holiday is None and not is_off:
            countable += 1
        entries.append({"date": d, "holidayName": holiday, "isOff": is_off})
    return {
        "days": entries,
        "workingDayCount": countable,
        "totalHours": countable * hours_per_day,
    }
