// Planning status page logic. Depends on app.js (API_BASE, apiRequest).

const POLL_INTERVAL_MS = 2500;

const STEP_ORDER = ['understanding', 'planning_strategy', 'searching_budget', 'building_itinerary'];

// Maps a raw status value from GET /trips/{id}/status to which step index
// is currently active. Everything before that index is "done", everything
// after is "pending". Unknown/null status means Concierge is still running
// (nothing written yet), so step 0 is active.
function activeStepIndexForStatus(status) {
  switch (status) {
    case 'planning': return 1;
    case 'searching_and_analyzing_budget': return 2;
    case 'building_itinerary': return 3;
    case 'awaiting_review':
    case 'finalized': return 4; // past the last step — everything done
    default: return 0; // null/unknown — Concierge running
  }
}

function renderSteps(status) {
  const activeIndex = activeStepIndexForStatus(status);
  STEP_ORDER.forEach((stepId, i) => {
    const el = document.getElementById(`step-${stepId}`);
    el.classList.remove('pending', 'active', 'done');
    if (i < activeIndex) el.classList.add('done');
    else if (i === activeIndex) el.classList.add('active');
    else el.classList.add('pending');
  });
}

function showSuccessAndRedirect(tripId) {
  document.getElementById('statusView').style.display = 'none';
  document.getElementById('successView').style.display = 'block';
  setTimeout(() => {
    window.location.href = `review.html?trip_id=${tripId}`;
  }, 2000);
}

async function pollStatus(tripId) {
  try {
    const data = await apiRequest(`/trips/${tripId}/status`);
    const status = data && data.status;

    renderSteps(status);

    if (status === 'awaiting_review' || status === 'finalized') {
      showSuccessAndRedirect(tripId);
      return; // stop polling
    }

    setTimeout(() => pollStatus(tripId), POLL_INTERVAL_MS);
  } catch (err) {
    // Transient network hiccups shouldn't kill the page — keep retrying,
    // but surface it quietly in case it's a real failure (e.g. trip not found).
    document.getElementById('pollError').textContent =
      `Having trouble checking status: ${err.message}. Retrying...`;
    document.getElementById('pollError').style.display = 'block';
    setTimeout(() => pollStatus(tripId), POLL_INTERVAL_MS);
  }
}

function init() {
  const params = new URLSearchParams(window.location.search);
  const tripId = params.get('trip_id');

  if (!tripId) {
    document.getElementById('pollError').textContent = 'No trip ID found in the URL.';
    document.getElementById('pollError').style.display = 'block';
    return;
  }

  renderSteps(null);
  pollStatus(tripId);
}

init();