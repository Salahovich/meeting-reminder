from datetime import datetime, timedelta, timezone

import requests

CALENDARVIEW_URL = "https://graph.microsoft.com/v1.0/me/calendarview"
SELECT_FIELDS = "id,subject,start,end,isOnlineMeeting,onlineMeeting,isCancelled"


class Meeting:
    def __init__(self, entry_id, subject, start, end, join_url):
        self.entry_id = entry_id
        self.subject = subject
        self.start = start  # naive local datetime
        self.end = end      # naive local datetime
        self.join_url = join_url

    def __repr__(self):
        return f"Meeting({self.subject!r}, {self.start}–{self.end}, joinable={bool(self.join_url)})"


def _parse_utc_to_local(date_time_str):
    # Graph returns e.g. "2026-06-22T03:43:00.0000000" when timeZone="UTC"
    dt = datetime.strptime(date_time_str.split(".")[0], "%Y-%m-%dT%H:%M:%S")
    dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None)


def _fetch(token, start_utc, end_utc, require_join_url):
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="UTC"',
    }
    params = {
        "startDateTime": start_utc.strftime("%Y-%m-%dT%H:%M:%S"),
        "endDateTime": end_utc.strftime("%Y-%m-%dT%H:%M:%S"),
        "$select": SELECT_FIELDS,
        "$orderby": "start/dateTime",
        "$top": "100",
    }
    response = requests.get(CALENDARVIEW_URL, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    events = response.json().get("value", [])

    meetings = []
    for event in events:
        if event.get("isCancelled"):
            continue
        join_url = (event.get("onlineMeeting") or {}).get("joinUrl")
        if require_join_url and not join_url:
            continue
        meetings.append(
            Meeting(
                entry_id=event["id"],
                subject=event.get("subject", "(no subject)"),
                start=_parse_utc_to_local(event["start"]["dateTime"]),
                end=_parse_utc_to_local(event["end"]["dateTime"]),
                join_url=join_url,
            )
        )
    return meetings


def get_upcoming_meetings(token, lookahead_minutes):
    now_utc = datetime.now(timezone.utc)
    end_utc = now_utc + timedelta(minutes=lookahead_minutes)
    return _fetch(token, now_utc, end_utc, require_join_url=True)


def get_todays_meetings(token):
    now_local = datetime.now()
    start_of_day_local = datetime(now_local.year, now_local.month, now_local.day)
    end_of_day_local = start_of_day_local + timedelta(days=1)
    # Convert local midnight boundaries to UTC for the query.
    start_utc = start_of_day_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_of_day_local.astimezone(timezone.utc).replace(tzinfo=None)
    return _fetch(token, start_utc, end_utc, require_join_url=False)
