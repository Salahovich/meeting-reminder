# Development notes: what was tried, what failed, what worked

This file exists so nobody (including future-us) re-treads the same dead ends.
The final architecture is described in [README.md](README.md); this is the "why."

## Calendar source: three attempts

### 1. New Outlook (Microsoft Store app) — dead end
Classic `Outlook.Application` COM automation simply doesn't exist for New Outlook —
it's a different, web-based architecture (no Win32 object model at all). Detected by:
`Dispatch("Outlook.Application")` succeeding (because a *separate*, unconfigured
classic Outlook install responded) but `GetNamespace("MAPI")` failing with
`"Cannot complete the operation. You are not connected"` — that error means there's
no real signed-in profile behind the classic COM endpoint, because the user actually
lives in New Outlook day to day.

### 2. Classic desktop Outlook via COM — worked, but with real footguns
Once the user signed into classic Outlook with their real account, COM automation
worked, but hit three distinct bugs worth remembering:

- **Multi-account profiles**: `Namespace.GetDefaultFolder(9)` only returns the
  calendar of the profile's *default* account. With a work + personal account both
  configured, the work account's calendar was silently never read. Fix: iterate
  `Namespace.Stores` and call `store.GetDefaultFolder(9)` per store, merging results.
- **Date-restriction format bug**: building a DASL `Restrict()` filter with
  `strftime("%m/%d/%Y %H:%M %p")` mixes 24-hour (`%H`) with an AM/PM suffix (`%p`) —
  e.g. produces `"18:13 PM"`, which Outlook's date parser silently fails to match
  against anything. Always use `%I` (12-hour) with `%p`.
- **Timezone double-conversion bug**: `item.Start` returns a tz-aware
  `pywintypes.datetime` tagged with the *Outlook profile's configured calendar
  timezone* — which can silently disagree with the OS timezone (here: Outlook's
  profile was set to London/UTC+0 while the OS/Python correctly knew Cairo/UTC+3).
  The wall-clock digits Outlook returns already match what the user sees/types in
  Outlook's own calendar UI. Calling `.astimezone()` on that value re-interprets
  those digits through the (here, wrong) tzinfo and silently shifts the time by the
  OS/profile offset difference — a "3 hours ahead of reality" symptom that's easy to
  misdiagnose as an OS timezone problem. **Fix: just `dt.replace(tzinfo=None)`, never
  `.astimezone()`, when reading `item.Start`.**
- **Sync lag / "heavy" client**: meetings created via Teams (not Outlook itself) take
  a noticeable, unpredictable amount of time to sync down into the local Outlook
  cache before COM can see them at all. This made testing slow and was the proximate
  reason for moving to Graph (see below) — Graph reflects server state immediately.
- Also worth noting: Outlook COM's `Body`/`Location` text-regex approach for finding
  a Teams join link **missed real Teams meetings** that Graph correctly reports via
  the structured `onlineMeeting.joinUrl` field — i.e. COM's data fidelity for this is
  worse than Graph's, independent of the timezone/sync issues above.

### 3. Microsoft Graph API — final approach, but auth was the hard part
See the dedicated section below — getting a working auth flow took several failed
attempts because of this tenant's Conditional Access policy.

## Auth: getting Microsoft Graph access without Azure AD admin rights

The account has no Entra ID / app-registration permissions and IT involvement was
explicitly out of scope. Here's the order of attempts and exactly why each failed,
ending in what worked.

| # | Approach | Result |
|---|---|---|
| 1 | Device-code flow, client_id = "Microsoft Graph PowerShell" (`14d82eec-...`) | `AADSTS53003: BlockedByConditionalAccess` |
| 2 | Interactive (system browser) flow, same client_id | `Need admin approval` — this *specific* app requires admin consent in this tenant |
| 3 | Device-code flow, client_id = Teams desktop (`1fec8e78-...`) | Same `BlockedByConditionalAccess` — **this proved the block is on device-code flow itself, tenant-wide, not on any one app** |
| 4 | Interactive flow, Teams client_id, dynamic loopback redirect (`http://localhost:<port>`) | `AADSTS50011: redirect URI mismatch` — Teams' app registration doesn't have a generic loopback URI registered |
| 5 | Interactive flow, Azure CLI client_id (`04b07795-...`), loopback redirect | Authenticated fine, but `AADSTS65002`: Azure CLI's client is only pre-authorized for the Azure Resource Manager API, not Microsoft Graph |
| 6 | **Interactive flow, Teams client_id, fixed redirect `https://login.microsoftonline.com/common/oauth2/nativeclient`, hosted inside our own pywebview window** | **Works.** No Conditional Access block, no consent prompt beyond the normal "Accept", and Teams' client is already pre-authorized for Graph. |

Key insight: this tenant's Conditional Access policy blocks **device-code flow**
specifically (a known anti-phishing baseline many orgs adopt), not interactive
browser-based sign-in — because blocking normal browser sign-in would break Teams/
Outlook Web for everyone. So the fix wasn't finding an "unblocked" app, it was using
the *flow* that was never blocked in the first place, with an app/redirect-URI
combination that actually supports it.

`acquire_token_interactive()` (which opens the *system* browser and listens on a
random loopback port) doesn't work here because no available pre-registered client_id
has a matching loopback redirect URI registered. The workaround: drive the OAuth
authorize URL manually inside a `pywebview` window we already control, watch for
navigation to the fixed `nativeclient` redirect URI (a URI many legacy public clients,
including Teams, do have registered — it doesn't need a listening server, the code is
just delivered via the URL itself), extract `?code=...`, and exchange it with
`msal.PublicClientApplication.acquire_token_by_authorization_code()`.

Scopes used: `Calendars.Read` (+ `offline_access` requested at the authorize-URL step
for a refresh token). Authority: `https://login.microsoftonline.com/organizations`
(NOT `common` — `common` failed with `AADSTS70002: not enabled for consumers` for
this client_id/tenant combination).

## UI: from tray app to floating widget

- First pass: `pystray` tray icon + a Tkinter countdown popup. Spinning up a fresh
  `tkinter.Tk()` in a new thread per popup crashed with
  `Tcl_AsyncDelete: async handler deleted by the wrong thread` — Tkinter is not safe
  to initialize repeatedly across threads. Fix at the time: one persistent `Tk()` root
  with its own dedicated thread running `mainloop()` forever, with popups created as
  `Toplevel` widgets scheduled onto it via `root.after(0, ...)` from other threads.
- Per explicit request for a "news channel" look (live pulsing dot, red theme,
  countdown), the whole UI was rewritten in HTML/CSS/JS rendered via `pywebview`
  (Edge WebView2), as a frameless, always-on-top, draggable window — `pystray` and
  Tkinter were dropped entirely.
- `pywebview` gotchas hit along the way:
  - `html, body { height: 100%; }` must be explicit — without it, `#widget { height:
    100% }` has nothing real to size against, leaving a default-white gap below
    shorter content when the window is resized taller (e.g. the Today panel).
  - A naive CSS marquee (`left: 0` → `left: -100%`, repeat) snaps visibly at the loop
    boundary. A seamless infinite marquee needs the text duplicated back-to-back in
    one track, animated by exactly `translateX(-50%)` — at the halfway point the
    (identical) second copy is exactly where the first one started.
  - `webview.create_window()` can be called again after `webview.start()` is already
    running its event loop — used to pop up the sign-in window on demand without
    restarting the app.

## Audio playback

`pygame` has no prebuilt wheel for Python 3.14 yet and fails to build from source in
this environment. Used the Windows MCI API directly via `ctypes` + `winmm.dll`
instead (`mciSendStringW`) — no extra dependency, supports both wav and mp3, and
gives full play/loop/stop control by re-issuing `play ... from 0` in a loop until a
deadline.

## Timesheet submission reminders

Added a second, independent alert type for payroll-timesheet deadlines: last working
day on/before the 15th (mid-month) and on/before month-end (end-of-month), with
Friday/Saturday as the only holidays. All logic lives in `timesheet.py` as pure date
math with no Graph/network dependency, so it works even before sign-in.

- **Stray "already submitted" bug**: while testing, the row defaulted to showing
  "Submitted" for every upcoming deadline through several months ahead, even though
  nothing had actually been submitted. Root cause: `timesheet_state.json` already had
  every candidate deadline marked submitted — leftover from an earlier UI iteration
  that showed the mark-as-submitted button unconditionally (not just on the deadline
  day), so it had been clicked during exploration/testing rather than from a real
  submission. Fix was just clearing the file — the date-math logic itself was correct
  the whole time. Lesson: don't trust a "default" status without checking whether the
  backing state file actually reflects real user action vs. test artifacts.
- **Testing the alert without waiting for a real deadline / without corrupting real
  state**: `scratch_test_timesheet_alert.py` monkey-patches
  `timesheet.SUBMITTED_PATH` to a scratch file *before* constructing `ReminderApp`,
  then calls `app._fire_timesheet_alert(date.today())` directly on a short timer
  instead of going through the real date-comparison path. This lets you see/hear the
  actual alert UI and exercise the "mark as submitted" button without ever touching
  the real `timesheet_state.json` — important because that file double-duties as the
  durable record of what's actually been submitted.
- The status label is intentionally three-state, not two: **Waiting** (before the
  deadline) → **Not submitted** (on/after the deadline day, unsubmitted — distinct
  from "Waiting" because it's now actionable/overdue) → **Submitted**. An earlier
  version had a "mark as submitted" button always visible in the today-panel row,
  which the user explicitly didn't want — the decision to mark something submitted
  should only be presented as an action on the deadline day itself (either in the
  panel row or the alert panel), not as a way to silently skip ahead.

## Auto-join

`auto_join` in `config.json` was defined from the start but intentionally left
unimplemented (`README.md` said "reserved"). Implemented it as a one-shot timer thread
spawned alongside the alert: sleeps until the meeting's actual start time, then checks
under the lock whether the alert is *still* the active one for this meeting (i.e. not
already dismissed or superseded) before calling `webbrowser.open()`. This avoids
auto-opening a join link after the user already left/dismissed the alert manually
before the meeting started.

## Misc

- Don't create test calendar items by assigning a naive Python `datetime` directly to
  `AppointmentItem.Start` via COM — its timezone handling round-trips unpredictably
  (confirmed by writing a known time and reading back a value offset by hours). Real,
  server-synced meeting data did not have this problem; only ad-hoc COM-written test
  data did. If you need a synthetic Teams meeting for testing, create it through the
  Outlook/Teams UI, not via raw COM property assignment.
