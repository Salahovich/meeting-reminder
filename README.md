# Meeting Reminder

A small always-on-top floating widget (styled like a news-channel "on air" ticker)
that watches your Microsoft 365 calendar for upcoming Teams meetings. A configurable
number of minutes before each one starts, it plays a looping countdown sound, pops up
a live countdown panel, and opens the meeting join link automatically.

## How it works

- The UI is a frameless HTML/CSS/JS widget rendered via [pywebview](https://pywebview.flowrl.com/)
  (Edge WebView2), anchored to the bottom-right of your screen — not a system tray app.
- Calendar data comes from the **Microsoft Graph API**, not desktop Outlook. Sign-in is
  a normal interactive browser-based Microsoft login (the same kind of login Teams/
  Outlook Web already use), not device-code — see [Auth](#auth) below for why.
- Every `poll_interval_seconds`, it fetches the next `lookahead_minutes` of calendar
  events and picks out the ones with a Teams `onlineMeeting.joinUrl`.
- At `alert_lead_minutes` before start: opens the join link in your default handler
  and shows a live countdown panel, looping `sound_file` until the meeting actually
  starts. The panel then stays up for `sound_loop_seconds` longer with a **REJOIN**
  button, in case you missed the auto-opened join link.
- Remembers which meetings it already alerted for (`state.json`) so it won't repeat,
  even across restarts.

## Auth

`graph_auth.py` uses Microsoft Teams desktop's own pre-registered public client ID —
it already exists in every Azure AD tenant, so there's no Azure app registration step.

Sign-in opens a small browser window for a normal Microsoft login + consent ("Accept")
prompt — a genuine interactive browser sign-in, not device-code. This matters: some
organizations block device-code flow specifically via Conditional Access (it's a
known phishing vector), while normal browser sign-in is essentially never blocked,
since that would break all web sign-ins org-wide. After the first sign-in, a refresh
token is cached in `token_cache.bin` so future runs are silent.

## Setup

1. Install dependencies (a venv is recommended):
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
2. Drop your own alert sound (wav or mp3) into `assets/`, e.g. `assets/countdown.mp3`,
   and point `config.json` → `sound_file` at it (path is relative to the project root).
3. Run it:
   ```
   .venv\Scripts\python run.py
   ```
   The widget appears bottom-right. If you haven't signed in yet, it shows a
   **SIGN IN** button — click it to complete the browser-based login once.
4. Click the hamburger icon for "Today's Schedule", or just leave it running — it'll
   auto-alert before each Teams meeting with a join link.

## Config (`config.json`)

| Key | Meaning |
|---|---|
| `sound_file` | Path to your alert sound (wav/mp3), relative to project root |
| `alert_lead_minutes` | How many minutes before meeting start to fire the alert |
| `sound_loop_seconds` | How long to keep the "rejoin" panel up after the meeting starts |
| `poll_interval_seconds` | How often to re-check the calendar |
| `lookahead_minutes` | How far ahead to scan for meetings |
| `auto_join` | If true, opens the Teams join link automatically when alerting |

## Running automatically at login

Create a shortcut to `start_silent.vbs` (included) in your Startup folder
(`Win+R` → `shell:startup`). It launches the widget with `pythonw.exe` so no console
window appears — the sign-in window (if needed) still appears normally since it's
part of the app's own UI, not a console prompt.

## Project layout

- `meeting_reminder/graph_auth.py` — interactive browser sign-in + token caching (MSAL).
- `meeting_reminder/graph_calendar.py` — fetches calendar events from Microsoft Graph.
- `meeting_reminder/sound_player.py` — loops a wav/mp3 via the Windows MCI API.
- `meeting_reminder/webui.py` — pywebview window lifecycle + the Python↔JS bridge.
- `meeting_reminder/main.py` — polling loop, alert triggering, app state.
- `assets/ui/` — the widget's HTML/CSS/JS.

## Notes / limitations

- Only events with a Teams `onlineMeeting.joinUrl` are treated as alertable meetings.
- `token_cache.bin` contains a refresh token — treat it like a credential (it's
  git-ignored already).
- The real BBC News countdown jingle is copyrighted and intentionally not bundled —
  bring your own royalty-free/owned sound file.
