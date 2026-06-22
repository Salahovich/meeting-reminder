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

window.showAlert = function (payload) {
  document.getElementById('bar').classList.add('hidden');
  document.getElementById('alertPanel').classList.remove('hidden');
  document.getElementById('todayPanel').classList.add('hidden');
  todayOpen = false;
  document.getElementById('alertSubject').textContent = payload.subject;
  alertStart = new Date(payload.startIso);
  joinUrl = payload.joinUrl || '';

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
      panel.classList.remove('hidden');
      window.pywebview.api.toggle_today(true);
    } else {
      panel.classList.add('hidden');
      window.pywebview.api.toggle_today(false);
    }
  });
});
