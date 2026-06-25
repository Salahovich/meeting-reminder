let state = null;
let signInStatus = 'unknown';
let idleDeadline = null;
let nextSubject = '';
let currentJoinUrl = '';
let todayOpen = false;
let lastView = null;
let lastAlertJson = null;
let lastTodayList = [];

// ---- formatting helpers ----

function fmtMMSS(ms) {
  if (ms <= 0) return '00:00';
  const totalSec = Math.ceil(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function fmtRemaining(ms) {
  if (ms <= 0) return 'now';
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s == null ? '' : s;
  return div.innerHTML;
}

// ---- backend calls ----

function postAction(name, body) {
  return fetch(`/api/actions/${name}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

// ---- confirm dialog ----
// Used before deselecting an already-marked day in the working-hours
// calendar or the office-days tracker, so a stray click can't silently wipe
// out a recorded day. Resolves true/false depending on which button is hit.
function confirmDialog(message) {
  return new Promise((resolve) => {
    const overlay = document.getElementById('confirmOverlay');
    const yesBtn = document.getElementById('confirmYesBtn');
    const noBtn = document.getElementById('confirmNoBtn');
    document.getElementById('confirmMessage').textContent = message;
    overlay.classList.remove('hidden');

    function cleanup(result) {
      overlay.classList.add('hidden');
      yesBtn.removeEventListener('click', onYes);
      noBtn.removeEventListener('click', onNo);
      resolve(result);
    }
    function onYes() {
      cleanup(true);
    }
    function onNo() {
      cleanup(false);
    }
    yesBtn.addEventListener('click', onYes);
    noBtn.addEventListener('click', onNo);
  });
}

// ---- idle ticker ----

function tickerText() {
  if (signInStatus === 'needs_sign_in') return 'SIGN IN TO SEE YOUR MEETINGS';
  if (signInStatus === 'signing_in') return 'SIGNING IN…';
  if (signInStatus === 'error') return 'SIGN-IN FAILED — TRY AGAIN';
  if (!idleDeadline) return 'NO UPCOMING MEETINGS';
  const remaining = idleDeadline - new Date();
  return `NEXT: ${nextSubject} · STARTS IN ${fmtRemaining(remaining)}`;
}

// Identifies whether the *meaningful* part of the ticker changed (subject/meeting),
// ignoring the countdown seconds which change every tick.
function tickerScrollKey() {
  return `${signInStatus}|${nextSubject}|${idleDeadline ? idleDeadline.toISOString().slice(0, 16) : ''}`;
}

let lastTickerText = null;
let lastScrollKey = null;

function adjustTickerScroll() {
  const wrap = document.querySelector('.ticker-wrap');
  const track = document.getElementById('tickerTrack');
  const itemA = document.getElementById('tickerA');
  const itemB = document.getElementById('tickerB');

  track.classList.remove('scrolling');
  itemB.classList.add('hidden');
  track.style.removeProperty('--ticker-duration');

  requestAnimationFrame(() => {
    if (itemA.scrollWidth > wrap.clientWidth) {
      itemB.classList.remove('hidden');
      const duration = Math.max(8, itemA.scrollWidth / 40);
      track.style.setProperty('--ticker-duration', `${duration}s`);
      track.classList.add('scrolling');
    }
  });
}

function tickIdle() {
  const text = tickerText();
  if (text !== lastTickerText) {
    lastTickerText = text;
    document.getElementById('tickerA').textContent = text;
    document.getElementById('tickerB').textContent = text;

    const scrollKey = tickerScrollKey();
    if (scrollKey !== lastScrollKey) {
      lastScrollKey = scrollKey;
      adjustTickerScroll();
    }
  }
}

// ---- today panel ----

function renderToday(list) {
  if (list) lastTodayList = list;
  const container = document.getElementById('todayList');
  container.innerHTML = '';
  if (!lastTodayList.length) {
    container.innerHTML = '<div class="today-empty">No meetings today</div>';
    return;
  }
  const now = new Date();
  lastTodayList.forEach((m) => {
    const start = m.startIso ? new Date(m.startIso) : null;
    const end = m.endIso ? new Date(m.endIso) : null;
    const isLive = start && end && start <= now && now < end;
    const isOverdue = start && end && now >= end;

    const row = document.createElement('div');
    let cls = 'today-row';
    if (isLive) cls += ' live-now';
    else if (isOverdue) cls += ' overdue';
    row.className = cls;

    const left = document.createElement('span');
    left.className = 'subject';
    left.innerHTML = `<span class="time-badge">${m.time}</span>${escapeHtml(m.subject)}`;
    row.appendChild(left);

    if (isLive && m.joinUrl) {
      const btn = document.createElement('button');
      btn.className = 'btn-live-join';
      btn.innerHTML = '<span class="live-dot"></span>&nbsp;JOIN';
      btn.addEventListener('click', () => postAction('join', { url: m.joinUrl }).then(poll));
      row.appendChild(btn);
    } else if (m.isTeams) {
      const tag = document.createElement('span');
      tag.className = 'tag-teams';
      tag.textContent = 'TEAMS';
      row.appendChild(tag);
    }

    container.appendChild(row);
  });
}

function renderTimesheet(payload) {
  const row = document.getElementById('timesheetRow');
  if (!row || !payload) return;
  row.className = 'today-row timesheet-row' + (payload.status === 'due' ? ' due' : '');

  const deadline = new Date(payload.deadlineIso);
  const dateLabel = deadline.toLocaleDateString(undefined, { day: '2-digit', month: 'short' });
  const periodLabel = payload.periodLabel === 'mid-month' ? 'Mid-month' : 'End-of-month';

  let statusClass, statusText;
  if (payload.status === 'submitted') {
    statusClass = 'status-submitted';
    statusText = 'Submitted';
  } else if (payload.status === 'due') {
    statusClass = 'status-due';
    statusText = 'Not submitted';
  } else {
    statusClass = 'status-next';
    statusText = 'Waiting';
  }

  row.innerHTML = '';
  const left = document.createElement('span');
  left.className = 'subject';
  left.innerHTML = `<span class="time-badge">${dateLabel}</span>${escapeHtml(periodLabel)} timesheet &middot; <span class="${statusClass}">${statusText}</span>`;
  row.appendChild(left);

  if (payload.status === 'due') {
    const btn = document.createElement('button');
    btn.className = 'btn-mark-submitted';
    btn.textContent = 'SUBMITTED';
    btn.addEventListener('click', () => postAction('mark_timesheet_submitted').then(poll));
    row.appendChild(btn);
  }
}

// Nothing counts as worked by default. A single click marks a day as worked
// (adding 1 day / hoursPerDay hours to the total); clicking it again unmarks
// it back to "remaining". isWorked is the day's current state at render
// time, captured in the closure, so the click always flips it.
function setWorked(dateIso, isWorked) {
  return postAction('set_worked', { dateIso, isWorked }).then(poll);
}

function wirePillClicks(pill, dateIso, isWorked) {
  pill.addEventListener('click', async () => {
    if (isWorked) {
      const ok = await confirmDialog('Unmark this day as worked?');
      if (!ok) return;
    }
    setWorked(dateIso, !isWorked);
  });
}

function renderWorkHoursPeriod(period, titleEl, rowEl, periodLabel) {
  titleEl.textContent =
    `${periodLabel} · ${period.workedDays}d/${period.workedHours}h worked · ` +
    `${period.remainingDays}d/${period.remainingHours}h remaining · ${period.holidayCount}d public holiday`;
  rowEl.innerHTML = '';
  period.days.forEach((d) => {
    const pill = document.createElement('button');
    let cls = 'workhours-day-pill';
    if (d.isHoliday) cls += ' holiday';
    else if (d.isWorked) cls += ' worked';
    if (d.isToday) cls += ' today';
    pill.className = cls;
    pill.textContent = d.label;
    pill.title = d.isHoliday ? d.holidayName : 'Click to mark/unmark as worked';
    if (d.isHoliday) {
      pill.disabled = true;
    } else {
      wirePillClicks(pill, d.dateIso, d.isWorked);
    }
    rowEl.appendChild(pill);
  });
}

function renderWorkHours(payload) {
  if (!payload) return;
  renderWorkHoursPeriod(
    payload,
    document.getElementById('workHoursTitle'),
    document.getElementById('workHoursDays'),
    payload.rangeLabel
  );
}

function renderOfficeDays(payload) {
  const summary = document.getElementById('officeSummary');
  const row = document.getElementById('officeDaysRow');
  if (!summary || !row || !payload) return;

  summary.textContent = `${payload.count}/${payload.minimum} this week`;
  summary.className = 'office-summary' + (payload.met ? ' met' : '');

  row.innerHTML = '';
  payload.days.forEach((d) => {
    const circle = document.createElement('button');
    let cls = 'office-day-circle';
    if (d.marked) cls += ' marked';
    if (d.isToday) cls += ' today';
    circle.className = cls;
    circle.textContent = d.label;
    circle.title = d.dateIso;
    circle.addEventListener('click', async () => {
      if (d.marked) {
        const ok = await confirmDialog('Unmark this office day?');
        if (!ok) return;
      }
      postAction('toggle_office_day', { dateIso: d.dateIso }).then(poll);
    });
    row.appendChild(circle);
  });
}

// ---- alert panel ----

function showMeetingAlert(alert) {
  document.getElementById('alertSubject').textContent = alert.subject;
  currentJoinUrl = alert.joinUrl || '';

  document.getElementById('countdown').classList.remove('hidden');
  document.getElementById('joinBtn').classList.remove('hidden');
  document.getElementById('submitBtn').classList.add('hidden');
  document.getElementById('officeMarkBtn').classList.add('hidden');

  const countdown = document.getElementById('countdown');
  countdown.classList.remove('live');
  const joinBtn = document.getElementById('joinBtn');
  joinBtn.classList.remove('btn-rejoin');
  joinBtn.classList.add('btn-join');
  const badge = document.getElementById('alertBadge');
  badge.className = 'breaking-badge';
  badge.innerHTML = '<span class="live-dot"></span>&nbsp;UPCOMING MEETING';

  tickMeetingCountdown(alert);
}

function tickMeetingCountdown(alert) {
  const el = document.getElementById('countdown');
  const badge = document.getElementById('alertBadge');
  const joinBtn = document.getElementById('joinBtn');
  const remaining = new Date(alert.startIso) - new Date();
  if (remaining <= 0) {
    el.textContent = 'LIVE';
    el.classList.add('live');
    joinBtn.textContent = 'REJOIN MEETING';
    joinBtn.classList.remove('btn-join');
    joinBtn.classList.add('btn-rejoin');
    badge.className = 'breaking-badge live';
    badge.innerHTML = '<span class="live-dot"></span>&nbsp;MEETING IN PROGRESS';
  } else {
    el.textContent = fmtMMSS(remaining);
    el.classList.remove('live');
    joinBtn.textContent = 'JOIN NOW';
    joinBtn.classList.remove('btn-rejoin');
    joinBtn.classList.add('btn-join');
  }
}

function showTimesheetAlert(alert) {
  const label = alert.periodLabel === 'mid-month' ? 'mid-month' : 'end-of-month';
  document.getElementById('alertSubject').textContent =
    `Submit your ${label} timesheet — due ${alert.deadlineText}.`;

  document.getElementById('countdown').classList.add('hidden');
  document.getElementById('joinBtn').classList.add('hidden');
  document.getElementById('submitBtn').classList.remove('hidden');
  document.getElementById('officeMarkBtn').classList.add('hidden');

  const badge = document.getElementById('alertBadge');
  badge.className = 'breaking-badge timesheet';
  badge.innerHTML = '<span class="live-dot"></span>&nbsp;TIMESHEET REMINDER';
}

function showOfficeAlert(alert) {
  const when = alert.isTomorrow ? `tomorrow (${alert.targetDateText})` : 'today';
  document.getElementById('alertSubject').textContent =
    `You haven't met your weekly office-day goal — plan to work from office ${when}.`;

  document.getElementById('countdown').classList.add('hidden');
  document.getElementById('joinBtn').classList.add('hidden');
  document.getElementById('submitBtn').classList.add('hidden');
  document.getElementById('officeMarkBtn').classList.remove('hidden');

  const badge = document.getElementById('alertBadge');
  badge.className = 'breaking-badge office';
  badge.innerHTML = '<span class="live-dot"></span>&nbsp;OFFICE DAY REMINDER';
}

function onAlertChanged(alert) {
  if (alert == null) return;
  // An alert always takes over the window; if the today panel happened to be
  // open, force it closed so dismissing/clearing the alert returns to idle,
  // not back to the panel — matches the original pywebview-era behavior.
  todayOpen = false;
  if (alert.kind === 'meeting') showMeetingAlert(alert);
  else if (alert.kind === 'timesheet') showTimesheetAlert(alert);
  else if (alert.kind === 'office') showOfficeAlert(alert);
}

// ---- alert sound ----

function updateAudio(alert) {
  const audio = document.getElementById('alertSound');
  if (!audio) return;
  let shouldPlay = false;
  if (alert) {
    if (alert.kind === 'meeting') {
      // Loops until the meeting actually starts, same cutoff as before.
      shouldPlay = new Date() < new Date(alert.startIso);
    } else {
      shouldPlay = true;
    }
  }
  if (shouldPlay && audio.paused) {
    audio.currentTime = 0;
    audio.play().catch(() => {});
  } else if (!shouldPlay && !audio.paused) {
    audio.pause();
    audio.currentTime = 0;
  }
}

// ---- view (idle / today / alert) ----

function desiredView() {
  if (state && state.alert) return 'alert';
  if (todayOpen) return 'today';
  return 'idle';
}

async function applyView(view) {
  // The header bar stays visible at all times except during an alert — the
  // Today panel is auxiliary content that stacks below it (the window just
  // grows taller), it doesn't replace it.
  document.getElementById('bar').classList.toggle('hidden', view === 'alert');
  document.getElementById('todayPanel').classList.add('hidden');
  document.getElementById('alertPanel').classList.add('hidden');
  // Resize the native window first, then reveal — avoids painting the panel
  // inside the still-previous-size window for one frame (visible stretch).
  await window.desktop.resizeWindow(view);
  if (view === 'today') {
    document.getElementById('todayPanel').classList.remove('hidden');
  } else if (view === 'alert') {
    document.getElementById('alertPanel').classList.remove('hidden');
    window.desktop.forceToFront();
  }
}

// ---- main render pass, driven by the poll loop ----

function render() {
  if (!state) return;

  signInStatus = state.signInStatus;
  const btn = document.getElementById('signInBtn');
  if (signInStatus === 'needs_sign_in') {
    btn.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'SIGN IN';
  } else if (signInStatus === 'signing_in') {
    btn.classList.remove('hidden');
    btn.disabled = true;
    btn.textContent = 'SIGNING IN…';
  } else if (signInStatus === 'error') {
    btn.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'RETRY SIGN IN';
  } else {
    btn.classList.add('hidden');
  }

  if (state.idle.hasNext) {
    idleDeadline = new Date(state.idle.startIso);
    nextSubject = (state.idle.subject || '').toUpperCase();
  } else {
    idleDeadline = null;
  }
  tickIdle();

  if (todayOpen) renderToday(state.todayMeetings);
  renderTimesheet(state.timesheet);
  renderWorkHours(state.workHours);
  renderOfficeDays(state.officeDays);

  const alertJson = JSON.stringify(state.alert);
  if (alertJson !== lastAlertJson) {
    lastAlertJson = alertJson;
    onAlertChanged(state.alert);
  }
  if (state.alert && state.alert.kind === 'meeting') {
    tickMeetingCountdown(state.alert);
  }
  updateAudio(state.alert);

  const view = desiredView();
  if (view !== lastView) {
    lastView = view;
    applyView(view);
  }
}

async function poll() {
  try {
    const res = await fetch('/api/state');
    state = await res.json();
    render();
  } catch (err) {
    console.error('poll failed', err);
  }
}

// ---- wiring ----

document.addEventListener('DOMContentLoaded', () => {
  setInterval(poll, 1000);
  poll();

  document.getElementById('joinBtn').addEventListener('click', () => {
    if (currentJoinUrl) {
      postAction('join', { url: currentJoinUrl });
      postAction('dismiss').then(poll);
    }
  });

  document.getElementById('dismissBtn').addEventListener('click', () => {
    postAction('dismiss').then(poll);
  });

  document.getElementById('submitBtn').addEventListener('click', () => {
    postAction('mark_timesheet_submitted').then(poll);
  });

  document.getElementById('officeMarkBtn').addEventListener('click', () => {
    postAction('mark_office_alert_day').then(poll);
  });

  document.getElementById('closeBtn').addEventListener('click', () => {
    window.desktop.quit();
  });

  document.getElementById('signInBtn').addEventListener('click', () => {
    window.desktop.signIn();
  });

  document.getElementById('todayBtn').addEventListener('click', () => {
    todayOpen = !todayOpen;
    render();
  });
});
