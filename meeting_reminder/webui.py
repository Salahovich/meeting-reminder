import ctypes
import os
import threading
import webbrowser

import webview

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_INDEX = os.path.join(ROOT_DIR, "assets", "ui", "index.html")

IDLE_SIZE = (380, 64)
TODAY_SIZE = (380, 340)
ALERT_SIZE = (380, 300)
MARGIN_X = 24
MARGIN_Y = 70  # leave room above the taskbar


def _screen_size():
    user32 = ctypes.windll.user32
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    # pywebview calls SetProcessDPIAware(), after which GetSystemMetrics returns
    # physical pixels. pywebview's window.move() expects logical pixels and
    # converts to physical internally.  Detect DPI awareness and undo the scaling
    # so callers always receive logical pixel dimensions.
    try:
        awareness = ctypes.c_int(0)
        ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(awareness))
        if awareness.value > 0:
            dpi = user32.GetDpiForSystem()
            scale = dpi / 96.0
            return int(w / scale), int(h / scale)
    except Exception:
        pass
    return w, h


def _bottom_right_position(width, height):
    screen_w, screen_h = _screen_size()
    return screen_w - width - MARGIN_X, screen_h - height - MARGIN_Y


def _apply_size(window, size):
    w, h = size
    window.resize(w, h)
    x, y = _bottom_right_position(w, h)
    window.move(x, y)


def set_idle_size(window):
    _apply_size(window, IDLE_SIZE)


def set_today_size(window):
    _apply_size(window, TODAY_SIZE)


def set_alert_size(window):
    _apply_size(window, ALERT_SIZE)


def force_to_front(window):
    """Make the alert visible over screen recorders / fullscreen apps.

    pywebview's on_top property toggles WinForms.Form.TopMost; flipping it
    True then False forces Windows to re-evaluate Z-order so the widget
    comes to the front but doesn't stay pinned afterwards.
    """
    try:
        window.on_top = True
        # Brief pin so Windows actually raises it above the current foreground
        threading.Timer(0.5, lambda: setattr(window, "on_top", False)).start()
    except Exception as exc:
        print(f"[webui] force_to_front failed: {exc!r}", flush=True)


class JsApi:
    """Methods here are exposed to the web UI as window.pywebview.api.<name>().

    The app reference is stored as _app (private) so pywebview's attribute
    reflection skips it — otherwise it would walk into ReminderApp → window →
    native WinForms Form → AccessibilityObject → Rectangle.Empty → ... and hit
    Python's recursion limit (logged but harmless noise).
    """

    def __init__(self, app):
        self._app = app

    def join_now(self, url):
        if url:
            webbrowser.open(url)

    def dismiss(self):
        self._app.dismiss_alert()

    def get_today_meetings(self):
        return self._app.get_today_meetings_payload()

    def toggle_today(self, open_):
        if open_:
            self._app.show_today_panel()
        else:
            self._app.hide_today_panel()

    def quit_app(self):
        self._app.request_quit()

    def sign_in(self):
        self._app.request_sign_in()

    def mark_timesheet_submitted(self):
        self._app.mark_timesheet_submitted()


def create_window(app):
    api = JsApi(app)
    x, y = _bottom_right_position(*IDLE_SIZE)
    window = webview.create_window(
        "Meeting Reminder",
        url=UI_INDEX,
        js_api=api,
        width=IDLE_SIZE[0],
        height=IDLE_SIZE[1],
        x=x,
        y=y,
        # pywebview's default min_size is (200, 100) which clamps our 64px-tall
        # bar-only state and shows ~36px of empty native-window background below.
        # Allow the native window to shrink to exact bar height.
        min_size=(IDLE_SIZE[0], IDLE_SIZE[1]),
        frameless=True,
        on_top=False,
        transparent=False,
        background_color='#0a0a0a',
        resizable=False,
        shadow=False,
    )
    return window
