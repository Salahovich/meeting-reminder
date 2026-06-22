import json
import threading
import time
import traceback
from datetime import datetime, timedelta

import webview

from . import graph_auth, graph_calendar, state, webui
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

        try:
            self.player.play(self.config["sound_file"], sound_duration)
        except FileNotFoundError:
            pass

    def hide_alert(self):
        with self.lock:
            self.alert_active = False
            self.alert_close_at = None
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
