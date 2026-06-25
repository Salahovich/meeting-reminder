# Meeting Reminder

A small floating widget (styled like a news-channel "on air" ticker) that watches your
Microsoft 365 calendar for upcoming Teams meetings, then plays a looping countdown
sound and pops a live MM:SS countdown panel a configurable number of minutes before
each one starts. After the meeting actually starts the panel stays up for half an
hour with a pulsing **REJOIN** button so a missed start isn't a missed meeting.

## How it works

- The UI is a frameless HTML/CSS/JS widget rendered via [pywebview](https://pywebview.flowrl.com/)
  (Edge WebView2), anchored to the bottom-right of your screen — not a system tray app.
  Not always-on-top: it sits behind other windows during normal use and only briefly
  pins itself to the top when an alert fires (so screen recorders / fullscreen apps
  can't hide it).
- Calendar data comes from the **Microsoft Graph API**, not desktop Outlook. Sign-in is
  a normal interactive browser-based Microsoft login (the same kind of login Teams/
  Outlook Web already use), not device-code — see [Auth](#auth) below for why.
- Every `poll_interval_seconds`, it refreshes the calendar and updates the ticker. A
  dedicated one-shot timer thread per meeting fires the alert at *exactly*
  `start − alert_lead_minutes`, so the alarm is on-time regardless of poll cadence.
- During the alert: the bar collapses, a full-panel countdown shows MM:SS, the
  alarm sound loops until meeting start, then the panel switches to **MEETING IN
  PROGRESS** with a green **REJOIN MEETING** button for `sound_loop_seconds` longer.
- The **Today's Schedule** panel (hamburger icon) lists every meeting on the calendar
  today. Meetings currently in progress get a live green **JOIN** button next to
  them, computed in real time from the meeting's start/end timestamps.
- If `auto_join` is enabled, the Teams link opens automatically the instant the
  countdown hits zero — no click needed, unless you already dismissed/joined first.
- Below the schedule, a **Next Timesheet Submission** row tracks your next payroll
  deadline (last working day on/before the 15th, and on/before month-end; Friday and
  Saturday count as holidays). It reads **Waiting** until the deadline day, then
  **Not submitted** with a mark-as-done control, then **Submitted** once confirmed.
  On the deadline day itself, it fires the same alert panel every hour from 8 AM to
  4 PM until you mark it submitted.
- Remembers which meetings it already alerted for (`state.json`) and which timesheet
  deadlines are submitted (`timesheet_state.json`), so neither repeats across restarts.

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
2. The default alert sound (`assets/countdown.mp3`) is bundled. To use your own,
   drop a wav/mp3 into `assets/` and point `config.json` → `sound_file` at it
   (path is relative to the project root).
3. Run it:
   ```
   .venv\Scripts\python run.py
   ```
   The widget appears bottom-right. If you haven't signed in yet, it shows a
   **SIGN IN** button — click it to complete the browser-based login once.
4. Click the hamburger icon for "Today's Schedule", or just leave it running — it'll
   auto-alert before each Teams meeting with a join link.

## Config (`config.json`)

Defaults live in `meeting_reminder/config.py`; create a `config.json` next to
`run.py` to override any of them.

| Key | Default | Meaning |
|---|---|---|
| `sound_file` | `assets/countdown.mp3` | Path to alert sound (wav/mp3), relative to project root |
| `alert_lead_minutes` | `1` | How many minutes before meeting start to fire the alert |
| `sound_loop_seconds` | `1800` | How long to keep the "REJOIN" panel up after the meeting starts (default: 30 min) |
| `poll_interval_seconds` | `5` | How often to re-check the calendar |
| `lookahead_minutes` | `60` | How far ahead to scan for meetings |
| `auto_join` | `false` | If `true`, opens the Teams join link automatically the instant the countdown hits zero (skipped if the alert was already dismissed/joined by then) |

## Running automatically at login

Create a shortcut to `start_silent.vbs` (included) in your Startup folder
(`Win+R` → `shell:startup`). It launches the widget with `pythonw.exe` so no console
window appears — the sign-in window (if needed) still appears normally since it's
part of the app's own UI, not a console prompt.

See [NOTES.md](NOTES.md) for the development history — failed approaches (and why),
bugs found, and the reasoning behind the final architecture.

## Project layout

- `meeting_reminder/graph_auth.py` — interactive browser sign-in + token caching (MSAL).
- `meeting_reminder/graph_calendar.py` — fetches calendar events from Microsoft Graph.
- `meeting_reminder/sound_player.py` — loops a wav/mp3 via the Windows MCI API.
- `meeting_reminder/webui.py` — pywebview window lifecycle + the Python↔JS bridge.
- `meeting_reminder/main.py` — polling loop, alert triggering, app state.
- `meeting_reminder/timesheet.py` — pure date math + persistence for the mid/end-of-month
  submission deadlines (no Graph/network dependency).
- `assets/ui/` — the widget's HTML/CSS/JS.
- `scratch_test_timesheet_alert.py` — manual test harness that opens the widget and
  fires a fake timesheet alert a couple seconds in, writing to a scratch state file
  instead of the real `timesheet_state.json` — use this instead of waiting for an
  actual deadline day to see the alert UI/sound.

## Notes / limitations

- Only events with a Teams `onlineMeeting.joinUrl` are treated as alertable meetings.
- `token_cache.bin` contains a refresh token — treat it like a credential (it's
  git-ignored already).
- The real BBC News countdown jingle is copyrighted and intentionally not bundled —
  bring your own royalty-free/owned sound file.
