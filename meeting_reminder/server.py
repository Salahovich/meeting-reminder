import os
import socket

from flask import Flask, jsonify, request, send_file, send_from_directory

from . import graph_auth

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(ROOT_DIR, "assets", "ui")
ASSETS_DIR = os.path.join(ROOT_DIR, "assets")

DEFAULT_PORT = 8765


def create_app(reminder_app):
    app = Flask(__name__, static_folder=UI_DIR, static_url_path="")

    @app.route("/")
    def index():
        return send_from_directory(UI_DIR, "index.html")

    @app.route("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(ASSETS_DIR, filename)

    @app.route("/api/sound")
    def sound():
        # Uses send_file (not send_from_directory) so a configured sound_file
        # outside assets/ still works, matching the old SoundPlayer's behavior.
        return send_file(reminder_app.config["sound_file"])

    @app.route("/api/state")
    def state():
        return jsonify(reminder_app.get_state_snapshot())

    @app.route("/api/auth/url")
    def auth_url():
        reminder_app.start_sign_in()
        return jsonify({"url": graph_auth.build_authorize_url()})

    @app.route("/api/auth/complete", methods=["POST"])
    def auth_complete():
        code = (request.get_json(silent=True) or {}).get("code", "")
        success, error = reminder_app.complete_sign_in(code)
        return jsonify({"success": success, "error": error})

    @app.route("/api/actions/dismiss", methods=["POST"])
    def dismiss():
        reminder_app.dismiss_alert()
        return jsonify({"ok": True})

    @app.route("/api/actions/join", methods=["POST"])
    def join():
        url = (request.get_json(silent=True) or {}).get("url", "")
        reminder_app.join_now(url)
        return jsonify({"ok": True})

    @app.route("/api/actions/mark_timesheet_submitted", methods=["POST"])
    def mark_timesheet_submitted():
        reminder_app.mark_timesheet_submitted()
        return jsonify({"ok": True})

    @app.route("/api/actions/toggle_office_day", methods=["POST"])
    def toggle_office_day():
        date_iso = (request.get_json(silent=True) or {}).get("dateIso", "")
        reminder_app.toggle_office_day(date_iso)
        return jsonify({"ok": True})

    @app.route("/api/actions/mark_office_alert_day", methods=["POST"])
    def mark_office_alert_day():
        reminder_app.mark_office_alert_day()
        return jsonify({"ok": True})

    @app.route("/api/actions/set_worked", methods=["POST"])
    def set_worked():
        body = request.get_json(silent=True) or {}
        reminder_app.set_worked(body.get("dateIso", ""), bool(body.get("isWorked")))
        return jsonify({"ok": True})

    return app


def _pick_port(preferred=DEFAULT_PORT):
    """Tries the preferred port first, falling back to an OS-assigned free one."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", preferred))
        port = preferred
    except OSError:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    s.close()
    return port


def run_server(reminder_app):
    port = _pick_port()
    app = create_app(reminder_app)
    reminder_app.run()  # starts the background poll_loop thread
    # First stdout line tells the parent process (Electron, or a human running this
    # standalone) which port to connect to.
    print(f"PORT={port}", flush=True)
    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)
