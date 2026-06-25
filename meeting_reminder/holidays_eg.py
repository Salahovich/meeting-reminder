"""Egypt national/public holidays, used to dim and exclude days from the work-hours
calendar. Fixed-date (Gregorian) holidays are computed for any year. Islamic/Coptic
calendar holidays shift every Gregorian year and are hard-coded per year below from
official estimates — Eid/Hijri dates depend on moon sighting and can shift by 1-2
days once announced; update MOVABLE_HOLIDAYS for each new year.
"""
from datetime import date

FIXED_HOLIDAYS = {
    (1, 7): "Coptic Christmas",
    (1, 25): "Revolution Day",
    (4, 25): "Sinai Liberation Day",
    (5, 1): "Labour Day",
    (6, 30): "June 30 Revolution",
    (7, 23): "July 23 Revolution",
    (10, 6): "Armed Forces Day",
}

MOVABLE_HOLIDAYS = {
    2026: {
        date(2026, 3, 20): "Eid al-Fitr",
        date(2026, 3, 21): "Eid al-Fitr",
        date(2026, 3, 22): "Eid al-Fitr",
        date(2026, 4, 13): "Sham El Nessim",
        date(2026, 5, 26): "Arafat Day",
        date(2026, 5, 27): "Eid al-Adha",
        date(2026, 5, 28): "Eid al-Adha",
        date(2026, 5, 29): "Eid al-Adha",
        date(2026, 6, 17): "Islamic New Year",
        date(2026, 8, 26): "Mawlid al-Nabi",
    },
}


def holidays_for_year(year):
    result = {date(year, m, d): name for (m, d), name in FIXED_HOLIDAYS.items()}
    result.update(MOVABLE_HOLIDAYS.get(year, {}))
    return result


def holiday_name(d):
    return holidays_for_year(d.year).get(d)
