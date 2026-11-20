// Planning status page logic with Mid-Crash Checkpoint Resumption
// Depends on app.js (API_BASE, apiRequest)

const POLL_INTERVAL_MS = 2500;
const STALL_TIMEOUT_MS = 45000; // If stuck on a step for >45s, show resume button
let lastStatusChangeTime = Date.now();
let lastSeenStatus = null;
let pollTimer = null;

const STEP_ORDER = ['understanding', 'planning_strategy', 'searching_budget', 'building_itinerary'];

function activeStepIndexForStatus(status) {
  switch (status) {
    case 'planning': return 1;
    case 'searching_and_analyzing_budget': return 2;
    case 'building_itinerary': return 3;
    case 'awaiting_review':
    case 'finalized': return 4;
    default: return 0;
  }
}

const PHASE_LABEL_IDS = ['understanding', 'strategy', 'searching', 'building'];

function updateSynthesisProgress(activeIndex) {
  const pct = Math.min(100, Math.round((activeIndex / STEP_ORDER.length) * 100));
  const pctEl = document.getElementById('synthesisPct');
  const badgeEl = document.getElementById('phaseBadge');
  const barEl = document.getElementById('synthesisBarFill');
  
  if (pctEl) pctEl.textContent = `${pct}%`;
  if (badgeEl) badgeEl.textContent = `Phase ${Math.min(activeIndex + 1, STEP_ORDER.length)} of ${STEP_ORDER.length}`;
  if (barEl) barEl.style.width = `${pct}%`;

  PHASE_LABEL_IDS.forEach((id, i) => {
    const el = document.getElementById(`label-${id}`);
    if (!el) return;
    el.classList.remove('active-label', 'done-label');
    if (i < activeIndex) el.classList.add('done-label');
    else if (i === activeIndex) el.classList.add('active-label');
  });
}

function renderSteps(status) {
  const activeIndex = activeStepIndexForStatus(status);
  STEP_ORDER.forEach((stepId, i) => {
    const el = document.getElementById(`step-${stepId}`);
    if (!el) return;
    el.classList.remove('pending', 'active', 'done');
    if (i < activeIndex) el.classList.add('done');
    else if (i === activeIndex) el.classList.add('active');
    else el.classList.add('pending');
  });
  updateSynthesisProgress(activeIndex);
}

function showSuccessAndRedirect(tripId) {
  const statusView = document.getElementById('statusView');
  const successView = document.getElementById('successView');
  if (statusView) statusView.style.display = 'none';
  if (successView) successView.style.display = 'block';
  setTimeout(() => {
    window.location.href = `review.html?trip_id=${tripId}`;
  }, 1800);
}

function showRecoveryUI(message) {
  const banner = document.getElementById('recoveryBanner');
  const msgEl = document.getElementById('recoveryMessage');
  if (banner && msgEl) {
    msgEl.textContent = message;
    banner.style.display = 'block';
  }
}

function hideRecoveryUI() {
  const banner = document.getElementById('recoveryBanner');
  if (banner) banner.style.display = 'none';
}

async function triggerResume(tripId) {
  const resumeBtn = document.getElementById('resumeBtn');
  if (resumeBtn) {
    resumeBtn.disabled = true;
    resumeBtn.textContent = 'Resuming...';
  }

  try {
    const res = await apiRequest(`/trips/${tripId}/resume`, { method: 'POST' });
    if (res && res.resumed) {
      hideRecoveryUI();
      lastStatusChangeTime = Date.now();
      pollStatus(tripId);
    } else {
      alert(res.message || 'Unable to resume at this time.');
    }
  } catch (err) {
    console.error('Resume error:', err);
    alert('Failed to connect to resume endpoint: ' + err.message);
  } finally {
    if (resumeBtn) {
      resumeBtn.disabled = false;
      resumeBtn.textContent = '🔄 Resume from Checkpoint';
    }
  }
}

async function pollStatus(tripId) {
  try {
    const data = await apiRequest(`/trips/${tripId}/status`);
    const status = data && data.status;

    // Track status transitions
    if (status !== lastSeenStatus) {
      lastSeenStatus = status;
      lastStatusChangeTime = Date.now();
      hideRecoveryUI();
    }

    renderSteps(status);

    if (status === 'awaiting_review' || status === 'finalized') {
      showSuccessAndRedirect(tripId);
      return; // done!
    }

    if (status === 'failed') {
      showRecoveryUI('Planning encountered an unexpected error. You can resume safely from the last saved state.');
      return;
    }

    // Check if stalled for too long (>45s on one step)
    if (Date.now() - lastStatusChangeTime > STALL_TIMEOUT_MS) {
      showRecoveryUI('Planning seems to be taking longer than usual. You can resume the process from the latest checkpoint.');
    }

    pollTimer = setTimeout(() => pollStatus(tripId), POLL_INTERVAL_MS);
  } catch (err) {
    // Surface quiet error and retry
    const pollError = document.getElementById('pollError');
    if (pollError) {
      pollError.textContent = `Connecting to server (${err.message})...`;
      pollError.style.display = 'block';
    }
    pollTimer = setTimeout(() => pollStatus(tripId), POLL_INTERVAL_MS);
  }
}

function init() {
  const params = new URLSearchParams(window.location.search);
  const tripId = params.get('trip_id');

  if (!tripId) {
    const pollError = document.getElementById('pollError');
    if (pollError) {
      pollError.textContent = 'No trip ID found in URL.';
      pollError.style.display = 'block';
    }
    return;
  }

  // Bind Resume Button click
  const resumeBtn = document.getElementById('resumeBtn');
  if (resumeBtn) {
    resumeBtn.addEventListener('click', () => triggerResume(tripId));
  }

  renderSteps(null);
  pollStatus(tripId);
}

init();