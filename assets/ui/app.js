let idleDeadline = null;   // Date of next meeting start, or null
let nextSubject = '';
let alertStart = null;     // Date the alerting meeting starts
let joinUrl = '';
let todayOpen = false;
let countdownTimer = null;
let signInStatus = 'unknown'; // unknown | needs_sign_in | signing_in | signed_in | error

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

let lastTickerText = null;

function tickIdle() {
  const text = tickerText();
  if (text !== lastTickerText) {
    lastTickerText = text;
    document.getElementById('tickerA').textContent = text;
    document.getElementById('tickerB').textContent = text;
    adjustTickerScroll();
  }
}

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
      const duration = Math.max(8, (itemA.scrollWidth / 40));
      track.style.setProperty('--ticker-duration', `${duration}s`);
      track.classList.add('scrolling');
    }
  });
}

function tickAlert() {
  const el = document.getElementById('countdown');
  const joinBtn = document.getElementById('joinBtn');
  if (!alertStart) return;
  const remaining = alertStart - new Date();
  if (remaining <= 0) {
    el.textContent = 'LIVE';
    joinBtn.textContent = 'REJOIN';
  } else {
    const totalSec = Math.floor(remaining / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    el.textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    joinBtn.textContent = 'JOIN NOW';
  }
}

function renderToday(list) {
  const container = document.getElementById('todayList');
  container.innerHTML = '';
  if (!list || !list.length) {
    container.innerHTML = '<div class="today-empty">No meetings today</div>';
    return;
  }
  list.forEach((m) => {
    const row = document.createElement('div');
    row.className = 'today-row' + (m.isOverdue ? ' overdue' : '');
    const left = document.createElement('span');
    left.className = 'subject';
    left.innerHTML = `<span class="time-badge">${m.time}</span>${escapeHtml(m.subject)}`;
    row.appendChild(left);

    if (m.isTeams) {
      const tag = document.createElement('span');
      tag.className = 'tag-teams';
      tag.textContent = 'TEAMS';
      row.appendChild(tag);
    }

    container.appendChild(row);
  });
}

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

window.showAlert = function (payload) {
  document.getElementById('alertPanel').classList.remove('hidden');
  document.getElementById('todayPanel').classList.add('hidden');
  todayOpen = false;
  document.getElementById('alertSubject').textContent = payload.subject;
  alertStart = new Date(payload.startIso);
  joinUrl = payload.joinUrl || '';

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
    if (joinUrl) window.pywebview.api.join_now(joinUrl);
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
      window.pywebview.api.get_today_meetings().then(renderToday);
    } else {
      panel.classList.add('hidden');
      window.pywebview.api.toggle_today(false);
    }
  });
});
