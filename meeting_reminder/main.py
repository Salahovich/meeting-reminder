import threading
import time
import traceback
import webbrowser
from datetime import date, datetime, timedelta

from . import graph_auth, graph_calendar, office_days, state, timesheet, work_hours
from .config import load_config

LATE_TRIGGER_GRACE_MINUTES = 5  # don't fire an alert for a meeting we noticed too late


class ReminderApp:
    def __init__(self):
        self.config = load_config()
        self.triggered = state.load_triggered_ids()
        self.lock = threading.Lock()

        self.alert_active = False
        self.alert_close_at = None
        self.active_alert_kind = None  # 'meeting' | 'timesheet' | 'office' | None
        self.current_alert = None  # kind-specific payload dict for the snapshot, or None

        self.access_token = None
        self.sign_in_status = "unknown"  # needs_sign_in | signing_in | signed_in | error
        self.sign_in_error = None

        self.scheduled = set()  # meeting IDs that have a _wait_and_fire thread
        self._today_cache = []  # last-fetched today payload
        self._idle_payload = {"hasNext": False}

        self.last_timesheet_alert_key = None  # (deadline_iso, hour) of last fired reminder
        self.last_office_alert_keys = set()  # {(kind, date_iso)} of fired office-day reminders
        self.office_alert_target_iso = None  # date the active office alert's button should mark

    # ---- auth ----

    def _ensure_token(self):
        with self.lock:
            if self.access_token:
                return self.access_token
        token = graph_auth.get_cached_access_token()
        with self.lock:
            self.access_token = token
        return token

    def start_sign_in(self):
        with self.lock:
            self.sign_in_status = "signing_in"

    def complete_sign_in(self, code):
        success, error = graph_auth.complete_sign_in(code)
        with self.lock:
            if success:
                self.access_token = graph_auth.get_cached_access_token()
                self.sign_in_status = "signed_in"
            else:
                self.sign_in_status = "error"
                self.sign_in_error = error
        return success, error

    # ---- background polling ----

    def poll_loop(self):
        while True:
            try:
                self._check_meetings()
            except Exception:
                traceback.print_exc()
            try:
                self._check_timesheet()
            except Exception:
                traceback.print_exc()
            try:
                self._check_office_days()
            except Exception:
                traceback.print_exc()
            self._check_alert_timeout()
            time.sleep(self.config["poll_interval_seconds"])

    def _check_alert_timeout(self):
        with self.lock:
            active = self.alert_active
            close_at = self.alert_close_at
        if active and close_at and time.time() >= close_at:
            self.hide_alert()

    def _check_meetings(self):
        token = self._ensure_token()
        if not token:
            with self.lock:
                if self.sign_in_status != "signing_in":
                    self.sign_in_status = "needs_sign_in"
            return
        with self.lock:
            self.sign_in_status = "signed_in"

        meetings = graph_calendar.get_upcoming_meetings(token, self.config["lookahead_minutes"])
        now = datetime.now()
        lead = timedelta(minutes=self.config["alert_lead_minutes"])

        upcoming = sorted(meetings, key=lambda m: m.start)

        # Fetch all of today's meetings: used for the idle-state header (shows meetings
        # beyond the 60-min alert window) and the today-panel cache (no blocking API
        # call per poll from the frontend — it just reads the cached snapshot).
        try:
            all_today = graph_calendar.get_todays_meetings(token)
            header_upcoming = sorted(
                [m for m in all_today if m.start > now], key=lambda m: m.start
            )
            with self.lock:
                self._today_cache = [
                    {
                        "time": m.start.strftime("%H:%M"),
                        "subject": m.subject,
                        "isTeams": bool(m.join_url),
                        "joinUrl": m.join_url or "",
                        "startIso": m.start.isoformat(),
                        "endIso": m.end.isoformat(),
                    }
                    for m in sorted(all_today, key=lambda m: m.start)
                ]
        except Exception:
            header_upcoming = upcoming

        if header_upcoming:
            next_m = header_upcoming[0]
            idle_payload = {"hasNext": True, "subject": next_m.subject, "startIso": next_m.start.isoformat()}
        else:
            idle_payload = {"hasNext": False}
        with self.lock:
            self._idle_payload = idle_payload

        for meeting in upcoming:
            if meeting.entry_id in self.triggered:
                continue

            trigger_time = meeting.start - lead
            too_late = now > meeting.start + timedelta(minutes=LATE_TRIGGER_GRACE_MINUTES)

            if too_late:
                self.triggered[meeting.entry_id] = time.time()
                state.save_triggered_ids(self.triggered)
                continue

            # Schedule a dedicated thread that sleeps until exactly trigger_time.
            # This fires the alert at the precise moment rather than relying on the
            # next poll cycle (which could be up to poll_interval seconds late).
            with self.lock:
                if meeting.entry_id in self.scheduled:
                    continue
                self.scheduled.add(meeting.entry_id)

            threading.Thread(
                target=self._wait_and_fire,
                args=(meeting, trigger_time),
                daemon=True,
            ).start()

    def _wait_and_fire(self, meeting, trigger_time):
        """Sleeps until trigger_time then fires the alert exactly on schedule."""
        delay = (trigger_time - datetime.now()).total_seconds()
        if delay > 0:
            time.sleep(delay)
        with self.lock:
            if meeting.entry_id in self.triggered:
                return  # already handled (too-late skip or duplicate)
            self.triggered[meeting.entry_id] = time.time()
        self._fire_alert(meeting)
        state.save_triggered_ids(self.triggered)

    def _check_timesheet(self):
        deadline = timesheet.get_next_deadline()
        if deadline is None:
            return
        now = datetime.now()
        if deadline != now.date():
            return
        if not (timesheet.ALERT_START_HOUR <= now.hour <= timesheet.ALERT_END_HOUR):
            return

        key = (deadline.isoformat(), now.hour)
        with self.lock:
            already_fired = self.last_timesheet_alert_key == key
            other_alert_active = self.alert_active
            if not already_fired and not other_alert_active:
                self.last_timesheet_alert_key = key
        if not already_fired and not other_alert_active:
            self._fire_timesheet_alert(deadline)

    def _fire_timesheet_alert(self, deadline):
        payload = {
            "kind": "timesheet",
            "periodLabel": timesheet.deadline_period_label(deadline),
            "deadlineText": deadline.strftime("%A, %d %b"),
        }
        with self.lock:
            self.alert_active = True
            self.active_alert_kind = "timesheet"
            self.alert_close_at = time.time() + self.config["sound_loop_seconds"]
            self.current_alert = payload

    def mark_timesheet_submitted(self):
        deadline = timesheet.get_next_deadline()
        if deadline:
            timesheet.mark_submitted(deadline)

        with self.lock:
            is_timesheet_alert = self.alert_active and self.active_alert_kind == "timesheet"
        if is_timesheet_alert:
            self.hide_alert()

    def _check_office_days(self):
        now = datetime.now()
        today = now.date()
        minimum = self.config["office_days_minimum"]

        if now.hour == office_days.MORNING_ALERT_HOUR and office_days.shortfall_today(minimum, today):
            self._maybe_fire_office_alert(("morning", today.isoformat()), today, evening=False)
        elif now.hour == office_days.EVENING_ALERT_HOUR and office_days.shortfall_tomorrow_evening(minimum, today):
            self._maybe_fire_office_alert(("evening", today.isoformat()), today + timedelta(days=1), evening=True)

    def _maybe_fire_office_alert(self, key, target_day, evening):
        with self.lock:
            already_fired = key in self.last_office_alert_keys
            other_alert_active = self.alert_active
            if not already_fired and not other_alert_active:
                self.last_office_alert_keys.add(key)
        if not already_fired and not other_alert_active:
            self._fire_office_alert(target_day, evening)

    def _fire_office_alert(self, target_day, evening):
        payload = {
            "kind": "office",
            "targetDateText": target_day.strftime("%A"),
            "isTomorrow": evening,
        }
        with self.lock:
            self.alert_active = True
            self.active_alert_kind = "office"
            self.alert_close_at = time.time() + self.config["sound_loop_seconds"]
            self.current_alert = payload
            self.office_alert_target_iso = target_day.isoformat()

    def toggle_office_day(self, date_iso):
        office_days.toggle_marked(date.fromisoformat(date_iso))

    def mark_office_alert_day(self):
        with self.lock:
            target_iso = self.office_alert_target_iso
            is_office_alert = self.alert_active and self.active_alert_kind == "office"

        if target_iso:
            office_days.mark(date.fromisoformat(target_iso))

        if is_office_alert:
            self.hide_alert()

    def set_worked(self, date_iso, is_worked):
        work_hours.set_worked(date.fromisoformat(date_iso), is_worked)

    def _fire_alert(self, meeting):
        seconds_until_start = max((meeting.start - datetime.now()).total_seconds(), 1)
        payload = {
            "kind": "meeting",
            "subject": meeting.subject,
            "startIso": meeting.start.isoformat(),
            "joinUrl": meeting.join_url or "",
        }
        with self.lock:
            self.alert_active = True
            self.active_alert_kind = "meeting"
            # The panel (with its "rejoin" button) stays up after the meeting starts
            # so a missed start isn't a missed meeting.
            self.alert_close_at = time.time() + seconds_until_start + self.config["sound_loop_seconds"]
            self.current_alert = payload

        if self.config.get("auto_join") and meeting.join_url:
            threading.Thread(
                target=self._auto_join_at_start,
                args=(meeting, seconds_until_start),
                daemon=True,
            ).start()

    def _auto_join_at_start(self, meeting, delay):
        """Opens the Teams link the moment the countdown reaches zero.

        Skipped if the alert was already dismissed (or superseded) by then,
        so a manual dismiss/join before start cancels the auto-open.
        """
        if delay > 0:
            time.sleep(delay)
        with self.lock:
            still_active = self.alert_active and self.active_alert_kind == "meeting"
        if still_active:
            webbrowser.open(meeting.join_url)

    def join_now(self, url):
        if url:
            webbrowser.open(url)

    def hide_alert(self):
        with self.lock:
            self.alert_active = False
            self.alert_close_at = None
            self.active_alert_kind = None
            self.current_alert = None

    def dismiss_alert(self):
        self.hide_alert()

    # ---- snapshot for GET /api/state ----

    def get_state_snapshot(self):
        with self.lock:
            alert = dict(self.current_alert) if self.current_alert else None
            sign_in_status = self.sign_in_status
            sign_in_error = self.sign_in_error
            today_cache = list(self._today_cache)
            idle_payload = dict(self._idle_payload)

        today = date.today()
        today_iso = today.isoformat()
        hours_per_day = self.config["work_hours_per_day"]
        period_days, range_label = work_hours.current_period_days(today)
        current_period = work_hours.period_summary(period_days, hours_per_day)

        def serialize_period(period):
            return {
                "workedDays": period["workedDays"],
                "remainingDays": period["remainingDays"],
                "workedHours": period["workedHours"],
                "remainingHours": period["remainingHours"],
                "holidayCount": period["holidayCount"],
                "days": [
                    {
                        "dateIso": d["date"].isoformat(),
                        "label": str(d["date"].day),
                        "isHoliday": d["holidayName"] is not None,
                        "holidayName": d["holidayName"] or "",
                        "isWorked": d["isWorked"],
                        "isToday": d["date"].isoformat() == today_iso,
                    }
                    for d in period["days"]
                ],
            }

        deadline, is_submitted = timesheet.get_relevant_deadline()
        timesheet_payload = None
        if deadline is not None:
            if is_submitted:
                ts_status = "submitted"
            elif deadline <= today:
                ts_status = "due"
            else:
                ts_status = "next"
            timesheet_payload = {
                "deadlineIso": deadline.isoformat(),
                "periodLabel": timesheet.deadline_period_label(deadline),
                "status": ts_status,
            }

        minimum = self.config["office_days_minimum"]
        office_status = office_days.get_week_status(minimum)
        office_payload = {
            "minimum": minimum,
            "count": office_status["count"],
            "met": office_status["met"],
            "days": [
                {
                    "dateIso": d.isoformat(),
                    "label": office_days.DAY_LABELS[d.weekday()],
                    "marked": d.isoformat() in office_status["markedSet"],
                    "isToday": d.isoformat() == today_iso,
                }
                for d in office_status["days"]
            ],
        }

        return {
            "signInStatus": sign_in_status,
            "signInError": sign_in_error,
            "alert": alert,
            "idle": idle_payload,
            "todayMeetings": today_cache,
            "timesheet": timesheet_payload,
            "workHours": {
                "hoursPerDay": hours_per_day,
                "rangeLabel": range_label,
                **serialize_period(current_period),
            },
            "officeDays": office_payload,
        }

    # ---- lifecycle ----

    def run(self):
        threading.Thread(target=self.poll_loop, daemon=True).start()
