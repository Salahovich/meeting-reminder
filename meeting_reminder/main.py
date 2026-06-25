import json
import threading
import time
import traceback
import webbrowser
from datetime import date, datetime, timedelta

import webview

from . import graph_auth, graph_calendar, office_days, state, timesheet, webui, work_hours
from .config import load_config
from .sound_player import SoundPlayer

LATE_TRIGGER_GRACE_MINUTES = 5  # don't fire an alert for a meeting we noticed too late


class ReminderApp:
    def __init__(self):
        self.config = load_config()
        self.triggered = state.load_triggered_ids()
        self.player = SoundPlayer()  # Plays audible alarm via Windows MCI
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.window = None
        self.alert_active = False
        self.alert_close_at = None
        self.today_panel_open = False
        self.access_token = None
        self.sign_in_in_progress = False
        self.scheduled = set()   # meeting IDs that have a _wait_and_fire thread
        self._today_cache = []   # last-fetched today payload, pushed to panel on open
        self.active_alert_kind = None  # 'meeting' | 'timesheet' | 'office' | None
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

    def request_sign_in(self):
        with self.lock:
            if self.sign_in_in_progress:
                return
            self.sign_in_in_progress = True
        self._eval_js("window.setSignInStatus('signing_in')")
        graph_auth.start_interactive_sign_in(self._on_sign_in_complete)

    def _on_sign_in_complete(self, success, error):
        with self.lock:
            self.sign_in_in_progress = False
        if success:
            self.access_token = graph_auth.get_cached_access_token()
            self._eval_js("window.setSignInStatus('signed_in')")
        else:
            self._eval_js(f"window.setSignInStatus('error', {json.dumps(error)})")

    # ---- background polling ----

    def poll_loop(self):
        while not self.stop_event.is_set():
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
            self.stop_event.wait(self.config["poll_interval_seconds"])

    def _check_alert_timeout(self):
        with self.lock:
            active = self.alert_active
            close_at = self.alert_close_at
        if active and close_at and time.time() >= close_at:
            self.hide_alert()

    def _check_meetings(self):
        token = self._ensure_token()
        if not token:
            self._eval_js("window.setSignInStatus('needs_sign_in')")
            return

        meetings = graph_calendar.get_upcoming_meetings(token, self.config["lookahead_minutes"])
        now = datetime.now()
        lead = timedelta(minutes=self.config["alert_lead_minutes"])

        upcoming = sorted(meetings, key=lambda m: m.start)

        # Fetch all of today's meetings: used for the idle-state header (shows meetings
        # beyond the 60-min alert window) and the today-panel cache (no blocking API
        # call on every panel open).
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

        self._push_idle_state(header_upcoming)

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
            # stop_event.wait returns True if the event is set (app quitting)
            if self.stop_event.wait(delay):
                return
        with self.lock:
            if meeting.entry_id in self.triggered:
                return  # already handled (too-late skip or duplicate)
            self.triggered[meeting.entry_id] = time.time()
        self._fire_alert(meeting)
        state.save_triggered_ids(self.triggered)

    def _check_timesheet(self):
        self._push_timesheet_status()

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
            meeting_alert_active = self.alert_active
            if not already_fired and not meeting_alert_active:
                self.last_timesheet_alert_key = key
        if not already_fired and not meeting_alert_active:
            self._fire_timesheet_alert(deadline)

    def _push_timesheet_status(self):
        with self.lock:
            if self.alert_active:
                return
            panel_open = self.today_panel_open
        if not panel_open:
            return
        deadline, is_submitted = timesheet.get_relevant_deadline()
        if deadline is None:
            return
        if is_submitted:
            status = "submitted"
        elif deadline <= date.today():
            status = "due"
        else:
            status = "next"
        payload = {
            "deadlineIso": deadline.isoformat(),
            "periodLabel": timesheet.deadline_period_label(deadline),
            "status": status,
        }
        self._eval_js(f"window.updateTimesheet({json.dumps(payload)})")

    def _fire_timesheet_alert(self, deadline):
        with self.lock:
            self.alert_active = True
            self.active_alert_kind = "timesheet"
            self.alert_close_at = time.time() + self.config["sound_loop_seconds"]
            self.today_panel_open = False

        if self.window:
            webui.set_alert_size(self.window)
            webui.force_to_front(self.window)
            payload = {
                "periodLabel": timesheet.deadline_period_label(deadline),
                "deadlineText": deadline.strftime("%A, %d %b"),
            }
            self._eval_js(f"window.showTimesheetAlert({json.dumps(payload)})")

        try:
            self.player.play(self.config["sound_file"], self.config["sound_loop_seconds"])
        except FileNotFoundError:
            pass

    def mark_timesheet_submitted(self):
        deadline = timesheet.get_next_deadline()
        if deadline:
            timesheet.mark_submitted(deadline)

        with self.lock:
            is_timesheet_alert = self.alert_active and self.active_alert_kind == "timesheet"
        if is_timesheet_alert:
            self.hide_alert()

        self._push_timesheet_status()

    def _check_office_days(self):
        self._push_office_days_status()

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

    def _push_office_days_status(self):
        with self.lock:
            if self.alert_active:
                return
            panel_open = self.today_panel_open
        if not panel_open:
            return
        minimum = self.config["office_days_minimum"]
        status = office_days.get_week_status(minimum)
        today_iso = date.today().isoformat()
        payload = {
            "minimum": minimum,
            "count": status["count"],
            "met": status["met"],
            "days": [
                {
                    "dateIso": d.isoformat(),
                    "label": office_days.DAY_LABELS[d.weekday()],
                    "marked": d.isoformat() in status["markedSet"],
                    "isToday": d.isoformat() == today_iso,
                }
                for d in status["days"]
            ],
        }
        self._eval_js(f"window.updateOfficeDays({json.dumps(payload)})")

    def _fire_office_alert(self, target_day, evening):
        with self.lock:
            self.alert_active = True
            self.active_alert_kind = "office"
            self.alert_close_at = time.time() + self.config["sound_loop_seconds"]
            self.today_panel_open = False
            self.office_alert_target_iso = target_day.isoformat()

        if self.window:
            webui.set_alert_size(self.window)
            webui.force_to_front(self.window)
            payload = {
                "targetDateText": target_day.strftime("%A"),
                "isTomorrow": evening,
            }
            self._eval_js(f"window.showOfficeAlert({json.dumps(payload)})")

        try:
            self.player.play(self.config["sound_file"], self.config["sound_loop_seconds"])
        except FileNotFoundError:
            pass

    def toggle_office_day(self, date_iso):
        office_days.toggle_marked(date.fromisoformat(date_iso))
        self._push_office_days_status()

    def mark_office_alert_day(self):
        with self.lock:
            target_iso = self.office_alert_target_iso
            is_office_alert = self.alert_active and self.active_alert_kind == "office"

        if target_iso:
            office_days.mark(date.fromisoformat(target_iso))

        if is_office_alert:
            self.hide_alert()

        self._push_office_days_status()

    def _push_work_hours_status(self):
        with self.lock:
            if self.alert_active:
                return
            panel_open = self.today_panel_open
        if not panel_open:
            return

        today = date.today()
        hours_per_day = self.config["work_hours_per_day"]
        first_half = work_hours.period_summary(
            work_hours.first_half_days(today.year, today.month), hours_per_day
        )
        second_half = work_hours.period_summary(
            work_hours.second_half_days(today.year, today.month), hours_per_day
        )
        today_iso = today.isoformat()

        def serialize(period):
            return {
                "totalHours": period["totalHours"],
                "workingDayCount": period["workingDayCount"],
                "days": [
                    {
                        "dateIso": d["date"].isoformat(),
                        "label": str(d["date"].day),
                        "isHoliday": d["holidayName"] is not None,
                        "holidayName": d["holidayName"] or "",
                        "isOff": d["isOff"],
                        "isToday": d["date"].isoformat() == today_iso,
                    }
                    for d in period["days"]
                ],
            }

        payload = {
            "hoursPerDay": hours_per_day,
            "firstHalf": serialize(first_half),
            "secondHalf": serialize(second_half),
        }
        self._eval_js(f"window.updateWorkHours({json.dumps(payload)})")

    def toggle_day_off(self, date_iso):
        work_hours.toggle_day_off(date.fromisoformat(date_iso))
        self._push_work_hours_status()

    def _push_idle_state(self, upcoming):
        with self.lock:
            if self.alert_active:
                return
            panel_open = self.today_panel_open
            today_cache = list(self._today_cache)
        if upcoming:
            next_m = upcoming[0]
            payload = {"hasNext": True, "subject": next_m.subject, "startIso": next_m.start.isoformat()}
        else:
            payload = {"hasNext": False}
        self._eval_js(f"window.updateIdle({json.dumps(payload)})")
        if panel_open:
            self._eval_js(f"window.updateTodayList({json.dumps(today_cache)})")

    def _fire_alert(self, meeting):
        with self.lock:
            self.alert_active = True
            self.active_alert_kind = "meeting"
            # Sound loops until the meeting actually starts; the panel (with its
            # "rejoin" button) then stays up a bit longer so a missed join can
            # still be recovered.
            seconds_until_start = max((meeting.start - datetime.now()).total_seconds(), 1)
            sound_duration = seconds_until_start
            self.alert_close_at = time.time() + seconds_until_start + self.config["sound_loop_seconds"]
            self.today_panel_open = False

        if self.window:
            webui.set_alert_size(self.window)
            # Briefly raise the widget above the current foreground app — keeps
            # the alarm visible even when a screen recorder or fullscreen window
            # covers the bottom-right corner.
            webui.force_to_front(self.window)
            payload = {
                "subject": meeting.subject,
                "startIso": meeting.start.isoformat(),
                "joinUrl": meeting.join_url or "",
            }
            self._eval_js(f"window.showAlert({json.dumps(payload)})")

        if self.config.get("auto_join") and meeting.join_url:
            threading.Thread(
                target=self._auto_join_at_start,
                args=(meeting, seconds_until_start),
                daemon=True,
            ).start()

        try:
            self.player.play(self.config["sound_file"], sound_duration)
        except FileNotFoundError:
            pass

    def _auto_join_at_start(self, meeting, delay):
        """Opens the Teams link the moment the countdown reaches zero.

        Skipped if the alert was already dismissed (or superseded) by then,
        so a manual dismiss/join before start cancels the auto-open.
        """
        if delay > 0 and self.stop_event.wait(delay):
            return
        with self.lock:
            still_active = self.alert_active and self.active_alert_kind == "meeting"
        if still_active:
            webbrowser.open(meeting.join_url)

    def hide_alert(self):
        with self.lock:
            self.alert_active = False
            self.alert_close_at = None
            self.active_alert_kind = None
        self.player.stop()
        self._eval_js("window.hideAlert()")
        if self.window:
            webui.set_idle_size(self.window)

    def _eval_js(self, code):
        if not self.window:
            return
        try:
            self.window.evaluate_js(code)
        except Exception:
            pass

    # ---- actions invoked from the web UI via JsApi ----

    def dismiss_alert(self):
        self.hide_alert()

    def get_today_meetings_payload(self):
        token = self._ensure_token()
        if not token:
            return []
        meetings = graph_calendar.get_todays_meetings(token)
        return [
            {
                "time": m.start.strftime("%H:%M"),
                "subject": m.subject,
                "isTeams": bool(m.join_url),
                "joinUrl": m.join_url or "",
                "startIso": m.start.isoformat(),
                "endIso": m.end.isoformat(),
            }
            for m in sorted(meetings, key=lambda m: m.start)
        ]

    def show_today_panel(self):
        with self.lock:
            if self.alert_active:
                return
            self.today_panel_open = True
            today_cache = list(self._today_cache)
        if self.window:
            webui.set_today_size(self.window)
            self._eval_js(f"window.updateTodayList({json.dumps(today_cache)})")
        self._push_timesheet_status()
        self._push_work_hours_status()
        self._push_office_days_status()
        # Reveal only after the window resize + content pushes are in,
        # so the panel paints once at final size with no growth animation.
        self._eval_js("window.revealTodayPanel()")

    def hide_today_panel(self):
        with self.lock:
            self.today_panel_open = False
            if self.alert_active:
                return
        if self.window:
            webui.set_idle_size(self.window)

    def request_quit(self):
        self.stop_event.set()
        self.player.stop()
        if self.window:
            self.window.destroy()

    # ---- lifecycle ----

    def run(self):
        self.window = webui.create_window(self)
        threading.Thread(target=self.poll_loop, daemon=True).start()
        webview.start()


def main():
    app = ReminderApp()
    app.run()


if __name__ == "__main__":
    main()
