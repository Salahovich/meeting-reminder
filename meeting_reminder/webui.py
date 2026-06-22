import ctypes
import os
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
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


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


class JsApi:
    """Methods here are exposed to the web UI as window.pywebview.api.<name>()."""

    def __init__(self, app):
        self.app = app

    def join_now(self, url):
        if url:
            webbrowser.open(url)

    def dismiss(self):
        self.app.dismiss_alert()

    def get_today_meetings(self):
        return self.app.get_today_meetings_payload()

    def toggle_today(self, open_):
        if open_:
            self.app.show_today_panel()
        else:
            self.app.hide_today_panel()

    def quit_app(self):
        self.app.request_quit()

    def sign_in(self):
        self.app.request_sign_in()


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
        frameless=True,
        on_top=True,
        transparent=True,
        resizable=False,
        shadow=False,
    )
    return window
