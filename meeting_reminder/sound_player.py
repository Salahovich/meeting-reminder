import ctypes
import os
import threading
import time

_winmm = ctypes.WinDLL("winmm.dll")
_winmm.mciSendStringW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
_winmm.mciSendStringW.restype = ctypes.c_uint

_ALIAS = "meeting_reminder_sound"


def _mci(command):
    buf = ctypes.create_unicode_buffer(255)
    _winmm.mciSendStringW(command, buf, 254, None)
    return buf.value


class SoundPlayer:
    """Plays a wav/mp3 file on loop for a fixed duration using the Windows MCI API."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def play(self, file_path, duration_seconds):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Sound file not found: {file_path}")

        self.stop()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, args=(file_path, duration_seconds), daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        with self._lock:
            _mci(f"stop {_ALIAS}")
            _mci(f"close {_ALIAS}")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self, file_path, duration_seconds):
        with self._lock:
            _mci(f"close {_ALIAS}")  # clean up any stale handle
            _mci(f'open "{file_path}" alias {_ALIAS}')

        deadline = time.time() + duration_seconds
        while time.time() < deadline and not self._stop_event.is_set():
            with self._lock:
                _mci(f"play {_ALIAS} from 0")

            while not self._stop_event.is_set() and time.time() < deadline:
                mode = _mci(f"status {_ALIAS} mode").strip().lower()
                if mode != "playing":
                    break
                time.sleep(0.2)

        with self._lock:
            _mci(f"stop {_ALIAS}")
            _mci(f"close {_ALIAS}")
