// Review page logic. Depends on app.js (API_BASE, apiRequest, fmtDate).

const POLL_INTERVAL_MS = 2500;
const MAX_POLL_ATTEMPTS = 24; // ~60s ceiling before surfacing a real error

let tripId = null;
let currentBudgetAnalysis = null;

function getTripId() {
  const params = new URLSearchParams(window.location.search);
  return params.get('trip_id');
}

async function loadItinerary() {
  const data = await apiRequest(`/trips/${tripId}/itinerary`);
  currentBudgetAnalysis = data.budget_analysis;
  renderTripHeader(data.itinerary, data.budget_analysis, { showSuggestionCta: true });
  renderDays(data.itinerary);
}

// ---------- chat ----------

function appendMessage(text, sender) {
  const msgEl = document.createElement('div');
  msgEl.className = `chat-msg ${sender}`;
  msgEl.textContent = text;
  const container = document.getElementById('chatMessages');
  container.appendChild(msgEl);
  container.scrollTop = container.scrollHeight;
}

function setInteractionsEnabled(enabled) {
  document.getElementById('chatInput').disabled = !enabled;
  document.getElementById('chatSendBtn').disabled = !enabled;
  document.getElementById('approveBtn').disabled = !enabled;
  document.querySelectorAll('.quick-chip').forEach(c => {
    c.style.pointerEvents = enabled ? 'auto' : 'none';
    c.style.opacity = enabled ? '1' : '0.5';
    c.style.cursor = enabled ? 'pointer' : 'not-allowed';
  });
}

function showUpdatingBanner(text) {
  const banner = document.getElementById('updatingBanner');
  banner.querySelector('span').textContent = text;
  banner.style.display = 'flex';
}
function hideUpdatingBanner() {
  document.getElementById('updatingBanner').style.display = 'none';
}

// Polls status until it has left "awaiting_review" and come back (edit path)
// or until it reaches "finalized" (approve path). Guards against reading the
// stale pre-edit status on the very first poll.
function pollUntilSettled({ targetStatus, onSettled, onTimeout, onError }) {
  let attempts = 0;
  let hasLeftAwaitingReview = false;

  async function tick() {
    attempts++;
    if (attempts > MAX_POLL_ATTEMPTS) {
      onTimeout();
      return;
    }

    try {
      const data = await apiRequest(`/trips/${tripId}/status`);
      const status = data && data.status;

      if (targetStatus === 'awaiting_review') {
        if (status && status !== 'awaiting_review') hasLeftAwaitingReview = true;
        if (hasLeftAwaitingReview && status === 'awaiting_review') {
          onSettled();
          return;
        }
      } else if (status === targetStatus) {
        onSettled();
        return;
      }

      setTimeout(tick, POLL_INTERVAL_MS);
    } catch (err) {
      // A 404 right after resume can happen transiently — keep retrying
      // up to the attempt ceiling rather than failing on the first blip.
      setTimeout(tick, POLL_INTERVAL_MS);
    }
  }

  tick();
}

async function sendEditMessage(text) {
  appendMessage(text, 'user');
  document.getElementById('chatInput').value = '';
  setInteractionsEnabled(false);
  showUpdatingBanner('Updating your itinerary...');

  try {
    await apiRequest(`/trips/${tripId}/review`, {
      method: 'POST',
      body: JSON.stringify({ action: 'edit', message: text })
    });

    pollUntilSettled({
      targetStatus: 'awaiting_review',
      onSettled: async () => {
        try {
          await loadItinerary();
          hideUpdatingBanner();
          appendMessage('Updated your itinerary.', 'system');
        } catch (err) {
          hideUpdatingBanner();
          appendMessage(`Couldn't load the updated itinerary: ${err.message}`, 'system');
        }
        setInteractionsEnabled(true);
      },
      onTimeout: () => {
        hideUpdatingBanner();
        appendMessage("This is taking longer than expected. Try refreshing the page in a moment.", 'system');
        setInteractionsEnabled(true);
      }
    });
  } catch (err) {
    hideUpdatingBanner();
    appendMessage(`Couldn't submit that edit: ${err.message}`, 'system');
    setInteractionsEnabled(true);
  }
}

// ---------- approve ----------

function showApproveConfirm() {
  document.getElementById('approveBtn').style.display = 'none';
  document.getElementById('approveConfirm').style.display = 'flex';
}
function hideApproveConfirm() {
  document.getElementById('approveBtn').style.display = 'flex';
  document.getElementById('approveConfirm').style.display = 'none';
}

async function confirmApprove() {
  hideApproveConfirm();
  setInteractionsEnabled(false);
  showUpdatingBanner('Finalizing your trip...');

  try {
    await apiRequest(`/trips/${tripId}/review`, {
      method: 'POST',
      body: JSON.stringify({ action: 'approve' })
    });

    pollUntilSettled({
      targetStatus: 'finalized',
      onSettled: () => {
        window.location.href = `final.html?trip_id=${tripId}`;
      },
      onTimeout: () => {
        hideUpdatingBanner();
        appendMessage("Finalizing is taking longer than expected. Try refreshing in a moment.", 'system');
        setInteractionsEnabled(true);
      }
    });
  } catch (err) {
    hideUpdatingBanner();
    appendMessage(`Couldn't finalize: ${err.message}`, 'system');
    setInteractionsEnabled(true);
  }
}

// ---------- init ----------

function init() {
  tripId = getTripId();
  if (!tripId) {
    document.body.innerHTML = '<div class="shell"><div class="submit-error" style="display:block;">No trip ID found in the URL.</div></div>';
    return;
  }

  loadItinerary().catch(err => {
    document.getElementById('pageError').textContent = `Couldn't load your itinerary: ${err.message}`;
    document.getElementById('pageError').style.display = 'block';
  });

  document.querySelectorAll('.quick-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.getElementById('chatInput').value = chip.dataset.text;
      document.getElementById('chatInput').focus();
    });
  });

  document.getElementById('chatSendBtn').addEventListener('click', () => {
    const text = document.getElementById('chatInput').value.trim();
    if (text) sendEditMessage(text);
  });

  document.getElementById('chatInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const text = e.target.value.trim();
      if (text) sendEditMessage(text);
    }
  });

  document.getElementById('approveBtn').addEventListener('click', showApproveConfirm);
  document.getElementById('cancelApproveBtn').addEventListener('click', hideApproveConfirm);
  document.getElementById('confirmApproveBtn').addEventListener('click', confirmApprove);
}

init();