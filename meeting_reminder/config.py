import json
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

DEFAULTS = {
    "sound_file": "assets/countdown.mp3",
    "alert_lead_minutes": 1,
    "sound_loop_seconds": 1800,  # 30 min — keeps the rejoin panel visible after meeting starts
    "poll_interval_seconds": 5,
    "lookahead_minutes": 60,
    "auto_join": False,
    "office_days_minimum": 1,
    "work_hours_per_day": 8,
}


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))

    sound_file = cfg["sound_file"]
    if not os.path.isabs(sound_file):
        cfg["sound_file"] = os.path.join(ROOT_DIR, sound_file)

    return cfg
