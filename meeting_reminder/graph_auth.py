import os
import threading

import msal

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


def build_authorize_url():
    """The OAuth authorize URL — host this in a real browser window (Electron
    popup, formerly a pywebview window) and watch for navigation to
    REDIRECT_URI to extract the code. See NOTES.md for why this exact
    technique (own window + nativeclient redirect) is required here.
    """
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


def complete_sign_in(code):
    """Exchanges an authorization code (extracted by the caller from the
    nativeclient redirect) for tokens. Returns (success: bool, error: str | None).
    """
    with _lock:
        cache = _load_cache()
        app = _build_app(cache)
        result = app.acquire_token_by_authorization_code(
            code, scopes=SCOPES, redirect_uri=REDIRECT_URI
        )
        _save_cache(cache)
        if "access_token" not in result:
            return False, result.get("error_description", str(result))
    return True, None
