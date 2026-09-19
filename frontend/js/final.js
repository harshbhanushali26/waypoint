let currentItinerary = null;

function getTripId() {
  const params = new URLSearchParams(window.location.search);
  return params.get('trip_id');
}

function getSampleKey() {
  const params = new URLSearchParams(window.location.search);
  return params.get('sample');
}

// ── Plain Text Export ───────────────────────────────────────────────────────

function textExportOf(itinerary) {
  const s = itinerary.trip_summary || {};
  const lines = [];

  lines.push(s.destination || 'Trip Itinerary');
  lines.push(`${fmtDate(s.start_date)} — ${fmtDate(s.end_date)} · ${s.num_travelers || 1} traveler(s)`);
  lines.push(`Total cost: ₹${(itinerary.total_cost || 0).toLocaleString('en-IN')}`);
  lines.push('');

  (itinerary.days || []).forEach((day, i) => {
    lines.push(`Day ${i + 1} — ${fmtDate(day.date)}`);
    (day.events || []).forEach(ev => {
      lines.push(`  [${fmtEventType(ev.type)}] ${ev.time || ''} ${ev.title}`);
      if (ev.details) lines.push(`      ${ev.details}`);
    });
    lines.push('');
  });

  return lines.join('\n');
}

function downloadItinerary(itinerary) {
  const text = textExportOf(itinerary);
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const destination = (itinerary.trip_summary && itinerary.trip_summary.destination) || 'trip';
  const safeName = destination.replace(/[^a-z0-9]+/gi, '-').toLowerCase();

  const a = document.createElement('a');
  a.href = url;
  a.download = `waypoint-${safeName}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ── Copy Link ───────────────────────────────────────────────────────────────

async function copyLink() {
  const btn = document.getElementById('copyLinkBtn');
  try {
    await navigator.clipboard.writeText(window.location.href);
    const original = btn.textContent;
    btn.textContent = 'Link copied!';
    setTimeout(() => { btn.textContent = original; }, 1800);
  } catch (err) {
    alert('Could not copy automatically — please copy the URL from your address bar.');
  }
}

// ── Bind Action Buttons ─────────────────────────────────────────────────────

function bindActionButtons(itinerary) {
  const dlBtn = document.getElementById('downloadBtn');
  if (dlBtn) {
    dlBtn.addEventListener('click', () => downloadItinerary(itinerary));
  }

  const cpBtn = document.getElementById('copyLinkBtn');
  if (cpBtn) {
    cpBtn.addEventListener('click', copyLink);
  }

  const calBtn = document.getElementById('calExportBtn');
  if (calBtn && typeof exportToICal === 'function') {
    calBtn.addEventListener('click', () => exportToICal(itinerary));
  }
}

// ── Page Initialization ─────────────────────────────────────────────────────

async function init() {
  const sampleKey = getSampleKey();
  const tripId = getTripId();

  // Mode 1: Instant load of static sample demo (?sample=goa)
  if (sampleKey) {
    try {
      const res = await fetch(`samples/${encodeURIComponent(sampleKey)}.json`);
      if (!res.ok) throw new Error('Sample fixture not found');
      const data = await res.json();

      currentItinerary = data.itinerary;
      renderTripHeader(data.itinerary, data.budget_analysis, { showSuggestionCta: false });
      renderDays(data.itinerary);
      bindActionButtons(data.itinerary);
      return;
    } catch (err) {
      console.warn('Could not load sample fixture:', err);
    }
  }

  // Mode 2: Live trip loading via API
  if (!tripId) {
    document.body.innerHTML = '<div class="shell"><div class="submit-error" style="display:block;">No trip ID found in the URL.</div></div>';
    return;
  }

  try {
    const data = await apiRequest(`/trips/${tripId}/itinerary`);
    currentItinerary = data.itinerary;
    renderTripHeader(data.itinerary, data.budget_analysis, { showSuggestionCta: false });
    renderDays(data.itinerary);
    bindActionButtons(data.itinerary);
  } catch (err) {
    document.getElementById('pageError').textContent = `Couldn't load your itinerary: ${err.message}`;
    document.getElementById('pageError').style.display = 'block';
  }
}

init();