# Meeting Reminder

A small floating widget (styled like a news-channel "on air" ticker) that watches your
Microsoft 365 calendar for upcoming Teams meetings, then plays a looping countdown
sound and pops a live MM:SS countdown panel a configurable number of minutes before
each one starts. After the meeting actually starts the panel stays up with a pulsing
**REJOIN** button so a missed start isn't a missed meeting. It also tracks payroll
timesheet deadlines, a weekly office-attendance goal, and a working-hours calendar —
each with its own alert.

## Architecture

- **Python backend** (`meeting_reminder/`) is a small local web server (Flask) — pure
  cross-platform logic with no OS-specific dependency. It polls the Microsoft Graph
  API for calendar events, runs all the alert/scheduling logic, and exposes a tiny
  JSON API (`GET /api/state`, `POST /api/actions/...`) plus the widget's own static
  assets and a `/api/sound` endpoint for the configured alert sound.
- **Electron** (`electron/`) is the native desktop shell — a frameless, draggable,
  bottom-right-anchored window. On launch it spawns the Python backend as a child
  process, reads back which port it picked, then points its `BrowserWindow` at
  `http://127.0.0.1:<port>/`. It owns everything that needs real OS access: window
  sizing/positioning (via Electron's cross-platform `screen` API), the brief
  always-on-top pulse when an alert fires, the sign-in popup window, and killing the
  backend on quit.
- **The widget UI** (`assets/ui/`) is plain HTML/CSS/JS, served by the Python backend
  and rendered by Electron. It polls `GET /api/state` once a second and re-renders
  from that single snapshot — there's no push channel; every user action is a
  `POST /api/actions/...` call.

This split means the backend alone is also just a normal local web app — you can run
it standalone (`run.py`) and open `http://127.0.0.1:<port>/` in any browser, no
Electron required, for debugging or on a platform you haven't set Electron up on yet.

## How it works

- Calendar data comes from the **Microsoft Graph API**, not desktop Outlook. Sign-in is
  a normal interactive browser-based Microsoft login (the same kind of login Teams/
  Outlook Web already use), not device-code — see [Auth](#auth) below for why.
- Every `poll_interval_seconds`, the backend refreshes the calendar and recomputes the
  ticker/alert state. A dedicated one-shot timer thread per meeting fires the alert at
  *exactly* `start − alert_lead_minutes`, so the alarm is on-time regardless of poll
  cadence — only the *display* of that state to the UI is on the 1-second poll cycle.
- During the alert: the bar collapses, a full-panel countdown shows MM:SS, the alarm
  sound loops until meeting start, then the panel switches to **MEETING IN PROGRESS**
  with a green **REJOIN MEETING** button for `sound_loop_seconds` longer.
- The **Today's Schedule** panel (hamburger icon) lists every meeting on the calendar
  today. Meetings currently in progress get a live green **JOIN** button next to
  them, computed in real time from the meeting's start/end timestamps.
- If `auto_join` is enabled, the Teams link opens automatically the instant the
  countdown hits zero — no click needed, unless you already dismissed/joined first.
- A **Next Timesheet Submission** row tracks your next payroll deadline (last working
  day on/before the 15th, and on/before month-end; Friday and Saturday count as
  holidays). It reads **Waiting** until the deadline day, then **Not submitted** with
  a mark-as-done control, then **Submitted** once confirmed. On the deadline day
  itself, it fires the same alert panel every hour from 8 AM to 4 PM until you mark it
  submitted.
- A **Working Hours** calendar shows the half of the current month containing today
  (1st–15th or 16th–end) as clickable day pills. Nothing counts as worked by default —
  click a day to mark it worked (adds 1 day / `work_hours_per_day` hours to the
  total); click again to unmark it (asks for confirmation first). Egyptian public
  holidays are dimmed and not clickable, and are excluded from both the worked and
  remaining counts.
- An **Office Days Tracker** shows the current week (Sunday–Thursday) as clickable
  pills — click a day to mark it as worked from office. If the weekly
  `office_days_minimum` isn't met, it fires a reminder alert both the evening before
  and the morning of any day still needed to reach it, and keeps reminding daily even
  if the goal becomes unreachable for that week.
- Unmarking an already-marked day (in either the working-hours calendar or the
  office-days tracker) shows a small centered confirm dialog first, so a stray click
  can't silently wipe out a recorded day.
- Remembers per-feature state across restarts: `state.json` (meetings already
  alerted), `timesheet_state.json` (submitted deadlines), `office_days_state.json`
  (marked office days), `worked_days_state.json` (marked work-hours days).

## Auth

`graph_auth.py` uses Microsoft Teams desktop's own pre-registered public client ID —
it already exists in every Azure AD tenant, so there's no Azure app registration step.

Sign-in opens a small Electron popup window for a normal Microsoft login + consent
("Accept") prompt — a genuine interactive browser sign-in, not device-code. This
matters: some organizations block device-code flow specifically via Conditional
Access (it's a known phishing vector), while normal browser sign-in is essentially
never blocked, since that would break all web sign-ins org-wide. Electron's main
process watches the popup's navigation for the redirect back to Microsoft's
`nativeclient` URI, extracts the auth code, and POSTs it to the backend
(`POST /api/auth/complete`) to finish the token exchange. After the first sign-in, a
refresh token is cached in `token_cache.bin` so future runs are silent.

## Setup

1. Install Python dependencies (a venv is recommended):
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
2. Install Electron's dependencies:
   ```
   cd electron
   npm install
   ```
3. The default alert sound (`assets/countdown.mp3`) is bundled. To use your own,
   drop a wav/mp3 anywhere and point `config.json` → `sound_file` at it (relative
   paths are resolved against the project root).
4. Run it:
   ```
   cd electron
   npm start
   ```
   This spawns the Python backend automatically and opens the widget bottom-right.
   If you haven't signed in yet, it shows a **SIGN IN** button — click it to complete
   the browser-based login once.
5. Click the hamburger icon for "Today's Schedule" (also shows the timesheet, working
   hours, and office-days sections), or just leave it running — it'll auto-alert
   before each Teams meeting with a join link.

## Config (`config.json`)

Defaults live in `meeting_reminder/config.py`; create a `config.json` next to
`run.py` to override any of them.

| Key | Default | Meaning |
|---|---|---|
| `sound_file` | `assets/countdown.mp3` | Path to alert sound (wav/mp3), served at `/api/sound` |
| `alert_lead_minutes` | `1` | How many minutes before meeting start to fire the alert |
| `sound_loop_seconds` | `1800` | How long to keep the "REJOIN" panel up after the meeting starts (default: 30 min); also how long timesheet/office alerts stay active |
| `poll_interval_seconds` | `5` | How often the backend re-checks the calendar |
| `lookahead_minutes` | `60` | How far ahead to scan for meetings |
| `auto_join` | `false` | If `true`, opens the Teams join link automatically the instant the countdown hits zero (skipped if the alert was already dismissed/joined by then) |
| `office_days_minimum` | `1` | Minimum office days required per week (Sun–Thu) before reminders fire |
| `work_hours_per_day` | `8` | Hours credited per day marked "worked" in the working-hours calendar |

## Running automatically at login

Create a shortcut to `start_silent.vbs` (included) in your Startup folder
(`Win+R` → `shell:startup`). It launches Electron directly (`electron.exe` against
the `electron/` folder) with no visible console window — Electron then spawns the
Python backend itself, same as `npm start`.

See [NOTES.md](NOTES.md) for the development history — failed approaches (and why),
bugs found, and the reasoning behind the architecture, including the pywebview → Electron migration.

## Project layout

- `meeting_reminder/graph_auth.py` — builds the OAuth URL and exchanges the auth code
  for tokens (MSAL); the popup window itself is opened by Electron, not Python.
- `meeting_reminder/graph_calendar.py` — fetches calendar events from Microsoft Graph.
- `meeting_reminder/server.py` — the Flask app: static asset serving, `/api/state`,
  `/api/actions/*`, `/api/auth/*`, `/api/sound`, and port selection.
- `meeting_reminder/main.py` — polling loop, alert triggering/scheduling, and the
  `get_state_snapshot()` that `/api/state` returns.
- `meeting_reminder/timesheet.py` — pure date math + persistence for the mid/end-of-month
  submission deadlines (no Graph/network dependency).
- `meeting_reminder/office_days.py` — pure date math + persistence for the weekly
  office-attendance tracker.
- `meeting_reminder/work_hours.py` — pure date math + persistence for the
  working-hours calendar (current half-month, marked days, holiday exclusion).
- `meeting_reminder/holidays_eg.py` — Egypt public holiday dates (fixed + yearly
  hard-coded Islamic/Coptic calendar dates — see the file's docstring for upkeep notes).
- `assets/ui/` — the widget's HTML/CSS/JS; polls `/api/state` and renders from it.
- `electron/` — `main.js` (window lifecycle, backend process management, IPC),
  `preload.js` (the minimal `window.desktop` bridge for native-only actions).
- `run.py` — starts the Flask backend standalone (no Electron) for debugging via curl
  or a plain browser tab.

## Notes / limitations

- Only events with a Teams `onlineMeeting.joinUrl` are treated as alertable meetings.
- `token_cache.bin` contains a refresh token — treat it like a credential (it's
  git-ignored already).
- The real BBC News countdown jingle is copyrighted and intentionally not bundled —
  bring your own royalty-free/owned sound file.
- The backend tries port 8765 first and falls back to an OS-assigned free port if
  that's taken; Electron reads back whichever port it actually used.
- Egypt's Islamic/Coptic-calendar holiday dates in `holidays_eg.py` are estimates
  that can shift by 1–2 days pending official moon-sighting confirmation, and only
  cover the years that have been added — update `MOVABLE_HOLIDAYS` for new years.
