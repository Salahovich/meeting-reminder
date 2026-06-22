import os
import threading
from urllib.parse import parse_qs, urlparse

import msal
import webview

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_CACHE_PATH = os.path.join(ROOT_DIR, "token_cache.bin")

# Microsoft Teams desktop app's own pre-registered public client ID — already
# pre-authorized for Microsoft Graph and not subject to this tenant's
# Conditional Access block on device-code flow, since this uses a genuine
# interactive browser sign-in instead (the same kind of login Teams/Outlook
# Web already use).
CLIENT_ID = "1fec8e78-bce4-4aaf-ab1b-5451cc387264"
AUTHORITY = "https://login.microsoftonline.com/organizations"
REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"
SCOPES = ["Calendars.Read"]

_lock = threading.Lock()


def _load_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_PATH):
        with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
            cache.deserialize(f.read())
    return cache


def _save_cache(cache):
    if cache.has_state_changed:
        with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
            f.write(cache.serialize())


def _build_app(cache):
    return msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)


def get_cached_access_token():
    """Returns an access token using only the cached refresh token (no UI).
    Returns None if there's no cached account or the refresh token is dead.
    """
    with _lock:
        cache = _load_cache()
        app = _build_app(cache)
        accounts = app.get_accounts()
        if not accounts:
            return None
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        _save_cache(cache)
        if result and "access_token" in result:
            return result["access_token"]
        return None


def _authorize_url():
    scope = "%20".join(SCOPES + ["offline_access"])
    return (
        f"{AUTHORITY}/oauth2/v2.0/authorize"
        f"?client_id={CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_mode=query"
        f"&scope={scope}"
        "&prompt=select_account"
    )


def start_interactive_sign_in(on_complete):
    """Opens a sign-in window (a real browser-based login, not device-code).
    on_complete(success: bool, error: str | None) is called once finished.
    Safe to call even while another pywebview window (e.g. the main widget)
    and its event loop are already running.
    """

    def handle_code(code):
        with _lock:
            cache = _load_cache()
            app = _build_app(cache)
            result = app.acquire_token_by_authorization_code(
                code, scopes=SCOPES, redirect_uri=REDIRECT_URI
            )
            if "access_token" not in result:
                _save_cache(cache)
                on_complete(False, result.get("error_description", str(result)))
                return
            _save_cache(cache)
        on_complete(True, None)

    def on_loaded():
        url = sign_in_window.get_current_url()
        if not url or not url.startswith(REDIRECT_URI):
            return
        params = parse_qs(urlparse(url).query)
        sign_in_window.destroy()
        if "code" in params:
            threading.Thread(target=handle_code, args=(params["code"][0],), daemon=True).start()
        else:
            error = params.get("error_description", params.get("error", ["Sign-in failed"]))[0]
            on_complete(False, error)

    sign_in_window = webview.create_window(
        "Sign in to Microsoft", url=_authorize_url(), width=480, height=640, on_top=True
    )
    sign_in_window.events.loaded += on_loaded
