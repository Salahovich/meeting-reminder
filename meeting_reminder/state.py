import json
import os
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT_DIR, "state.json")
MAX_AGE_SECONDS = 2 * 24 * 60 * 60  # prune entries older than 2 days


def load_triggered_ids():
    """Returns {entry_id: trigger_timestamp}, pruned of stale entries."""
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    cutoff = time.time() - MAX_AGE_SECONDS
    return {k: v for k, v in data.items() if v >= cutoff}


def save_triggered_ids(triggered):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(triggered, f)
