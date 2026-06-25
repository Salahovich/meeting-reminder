let idleDeadline = null;
let nextSubject = '';
let alertStart = null;
let joinUrl = '';
let todayOpen = false;
let countdownTimer = null;
let signInStatus = 'unknown';

// ---- ticker ----

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
    // Update both spans in-place so the CSS animation keeps running uninterrupted.
    document.getElementById('tickerA').textContent = text;
    document.getElementById('tickerB').textContent = text;

    // Only restart the CSS animation when the meeting/subject changes,
    // not on every countdown-second update (which would reset the animation each tick).
    const scrollKey = tickerScrollKey();
    if (scrollKey !== lastScrollKey) {
      lastScrollKey = scrollKey;
      adjustTickerScroll();
    }
  }
}

// ---- alert countdown ----

function tickAlert() {
  const el = document.getElementById('countdown');
  const badge = document.getElementById('alertBadge');
  const joinBtn = document.getElementById('joinBtn');
  if (!alertStart) return;
  const remaining = alertStart - new Date();
  if (remaining <= 0) {
    el.textContent = 'LIVE';
    el.classList.add('live');
    joinBtn.textContent = 'REJOIN MEETING';
    joinBtn.classList.remove('btn-join');
    joinBtn.classList.add('btn-rejoin');
    if (badge) {
      badge.className = 'breaking-badge live';
      badge.innerHTML = '<span class="live-dot"></span>&nbsp;MEETING IN PROGRESS';
    }
  } else {
    el.textContent = fmtMMSS(remaining);
    el.classList.remove('live');
    joinBtn.textContent = 'JOIN NOW';
    joinBtn.classList.remove('btn-rejoin');
    joinBtn.classList.add('btn-join');
    // Badge keeps its static "UPCOMING MEETING" label — no countdown in the badge
  }
}

// ---- today panel ----

let lastTodayList = [];

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
    // Compute live/overdue at render time from the absolute timestamps —
    // never stale, no matter when the cache was last pushed.
    const start = m.startIso ? new Date(m.startIso) : null;
    const end   = m.endIso   ? new Date(m.endIso)   : null;
    const isLive    = start && end && start <= now && now < end;
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
      btn.addEventListener('click', () => window.pywebview.api.join_now(m.joinUrl));
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

// Re-render every second so meetings transition through upcoming -> live ->
// overdue without waiting for the next Python push.
setInterval(() => {
  if (todayOpen) renderToday(null);
}, 1000);

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s == null ? '' : s;
  return div.innerHTML;
}

// ---- functions called by Python via evaluate_js ----

window.updateIdle = function (payload) {
  if (payload.hasNext) {
    idleDeadline = new Date(payload.startIso);
    nextSubject = (payload.subject || '').toUpperCase();
  } else {
    idleDeadline = null;
  }
  tickIdle();
};

// Called by Python (via evaluate_js) to refresh the today list while the panel is open.
// Using a Python-push avoids a concurrent JS→Python API call that can deadlock the bridge.
window.updateTodayList = function (list) {
  if (todayOpen) {
    renderToday(list);
  }
};

// Called by Python to refresh the "next timesheet submission" row while the panel is open.
// This is read-only display — the user marks a timesheet submitted from the
// hourly alert panel itself, or via the button shown here only on the deadline day.
window.updateTimesheet = function (payload) {
  const row = document.getElementById('timesheetRow');
  if (!row) return;
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
    btn.addEventListener('click', () => window.pywebview.api.mark_timesheet_submitted());
    row.appendChild(btn);
  }
};

// Called by Python to refresh the working-hours calendar while the panel is open.
function renderWorkHoursPeriod(period, titleEl, rowEl, periodLabel) {
  titleEl.textContent = `${periodLabel} · ${period.workingDayCount}d · ${period.totalHours}h`;
  rowEl.innerHTML = '';
  period.days.forEach((d) => {
    const pill = document.createElement('button');
    let cls = 'workhours-day-pill';
    if (d.isHoliday) cls += ' holiday';
    else if (d.isOff) cls += ' off';
    if (d.isToday) cls += ' today';
    pill.className = cls;
    pill.textContent = d.label;
    pill.title = d.isHoliday ? d.holidayName : d.dateIso;
    if (d.isHoliday) {
      pill.disabled = true;
    } else {
      pill.addEventListener('click', () => window.pywebview.api.toggle_day_off(d.dateIso));
    }
    rowEl.appendChild(pill);
  });
}

window.updateWorkHours = function (payload) {
  renderWorkHoursPeriod(
    payload.firstHalf,
    document.getElementById('firstHalfTitle'),
    document.getElementById('firstHalfDays'),
    '1–15'
  );
  renderWorkHoursPeriod(
    payload.secondHalf,
    document.getElementById('secondHalfTitle'),
    document.getElementById('secondHalfDays'),
    '16–end'
  );
};

// Called by Python to refresh the office-days row while the panel is open.
window.updateOfficeDays = function (payload) {
  const summary = document.getElementById('officeSummary');
  const row = document.getElementById('officeDaysRow');
  if (!summary || !row) return;

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
    circle.addEventListener('click', () => window.pywebview.api.toggle_office_day(d.dateIso));
    row.appendChild(circle);
  });
};

window.showAlert = function (payload) {
  document.getElementById('bar').classList.add('hidden');
  document.getElementById('alertPanel').classList.remove('hidden');
  document.getElementById('todayPanel').classList.add('hidden');
  todayOpen = false;
  document.getElementById('alertSubject').textContent = payload.subject;
  alertStart = new Date(payload.startIso);
  joinUrl = payload.joinUrl || '';

  // Reset to the "meeting" layout in case a timesheet alert left it switched.
  document.getElementById('countdown').classList.remove('hidden');
  document.getElementById('joinBtn').classList.remove('hidden');
  document.getElementById('submitBtn').classList.add('hidden');
  document.getElementById('officeMarkBtn').classList.add('hidden');

  // Reset live-state classes from any previous alert
  const countdown = document.getElementById('countdown');
  countdown.classList.remove('live');
  const joinBtn = document.getElementById('joinBtn');
  joinBtn.classList.remove('btn-rejoin');
  joinBtn.classList.add('btn-join');
  const badge = document.getElementById('alertBadge');
  if (badge) {
    badge.className = 'breaking-badge';
    badge.innerHTML = '<span class="live-dot"></span>&nbsp;UPCOMING MEETING';
  }

  tickAlert();
  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = setInterval(tickAlert, 500);
};

window.showTimesheetAlert = function (payload) {
  document.getElementById('bar').classList.add('hidden');
  document.getElementById('alertPanel').classList.remove('hidden');
  document.getElementById('todayPanel').classList.add('hidden');
  todayOpen = false;

  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
  alertStart = null;

  const label = payload.periodLabel === 'mid-month' ? 'mid-month' : 'end-of-month';
  document.getElementById('alertSubject').textContent =
    `Submit your ${label} timesheet — due ${payload.deadlineText}.`;

  document.getElementById('countdown').classList.add('hidden');
  document.getElementById('joinBtn').classList.add('hidden');
  document.getElementById('submitBtn').classList.remove('hidden');
  document.getElementById('officeMarkBtn').classList.add('hidden');

  const badge = document.getElementById('alertBadge');
  if (badge) {
    badge.className = 'breaking-badge timesheet';
    badge.innerHTML = '<span class="live-dot"></span>&nbsp;TIMESHEET REMINDER';
  }
};

window.showOfficeAlert = function (payload) {
  document.getElementById('bar').classList.add('hidden');
  document.getElementById('alertPanel').classList.remove('hidden');
  document.getElementById('todayPanel').classList.add('hidden');
  todayOpen = false;

  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
  alertStart = null;

  const when = payload.isTomorrow ? `tomorrow (${payload.targetDateText})` : 'today';
  document.getElementById('alertSubject').textContent =
    `You haven't met your weekly office-day goal — plan to work from office ${when}.`;

  document.getElementById('countdown').classList.add('hidden');
  document.getElementById('joinBtn').classList.add('hidden');
  document.getElementById('submitBtn').classList.add('hidden');
  document.getElementById('officeMarkBtn').classList.remove('hidden');

  const badge = document.getElementById('alertBadge');
  if (badge) {
    badge.className = 'breaking-badge office';
    badge.innerHTML = '<span class="live-dot"></span>&nbsp;OFFICE DAY REMINDER';
  }
};

window.setSignInStatus = function (status, error) {
  signInStatus = status;
  const btn = document.getElementById('signInBtn');
  if (status === 'needs_sign_in') {
    btn.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'SIGN IN';
  } else if (status === 'signing_in') {
    btn.classList.remove('hidden');
    btn.disabled = true;
    btn.textContent = 'SIGNING IN…';
  } else if (status === 'error') {
    btn.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'RETRY SIGN IN';
    console.error('Sign-in error:', error);
  } else {
    btn.classList.add('hidden');
  }
  tickIdle();
};

// Called by Python after it has resized the native window to TODAY_SIZE and pushed
// the initial data — only then do we un-hide the panel, avoiding the brief moment
// where the panel would otherwise paint inside the still-bar-height window.
window.revealTodayPanel = function () {
  document.getElementById('todayPanel').classList.remove('hidden');
};

window.hideAlert = function () {
  document.getElementById('bar').classList.remove('hidden');
  document.getElementById('alertPanel').classList.add('hidden');
  document.getElementById('todayPanel').classList.add('hidden');
  todayOpen = false;
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
};

// ---- wiring ----

function whenReady(cb) {
  let domReady = false;
  let apiReady = false;
  function check() {
    if (domReady && apiReady) cb();
  }
  document.addEventListener('DOMContentLoaded', () => {
    domReady = true;
    check();
  });
  window.addEventListener('pywebviewready', () => {
    apiReady = true;
    check();
  });
}

whenReady(() => {
  setInterval(tickIdle, 1000);
  tickIdle();

  document.getElementById('joinBtn').addEventListener('click', () => {
    if (joinUrl) {
      window.pywebview.api.join_now(joinUrl);
      window.pywebview.api.dismiss();
    }
  });

  document.getElementById('dismissBtn').addEventListener('click', () => {
    window.pywebview.api.dismiss();
  });

  document.getElementById('submitBtn').addEventListener('click', () => {
    window.pywebview.api.mark_timesheet_submitted();
  });

  document.getElementById('officeMarkBtn').addEventListener('click', () => {
    window.pywebview.api.mark_office_alert_day();
  });

  document.getElementById('closeBtn').addEventListener('click', () => {
    window.pywebview.api.quit_app();
  });

  document.getElementById('signInBtn').addEventListener('click', () => {
    window.pywebview.api.sign_in();
  });

  document.getElementById('todayBtn').addEventListener('click', () => {
    todayOpen = !todayOpen;
    const panel = document.getElementById('todayPanel');
    if (todayOpen) {
      // Don't un-hide here — Python resizes the native window first, then calls
      // window.revealTodayPanel() so the panel only paints at full size (no
      // visible stretch from bar-height to full-height).
      window.pywebview.api.toggle_today(true);
    } else {
      panel.classList.add('hidden');
      window.pywebview.api.toggle_today(false);
    }
  });
});
