// Final (read-only) itinerary page logic.
// Depends on app.js (API_BASE, apiRequest, fmtDate) and itinerary-render.js
// (renderTripHeader, renderDays, fmtEventType).

let tripId = null;

function getTripId() {
  const params = new URLSearchParams(window.location.search);
  return params.get('trip_id');
}

function textExportOf(itinerary) {
  const s = itinerary.trip_summary;
  const lines = [];

  lines.push(s.destination);
  lines.push(`${fmtDate(s.start_date)} — ${fmtDate(s.end_date)} · ${s.num_travelers} traveler(s)`);
  lines.push(`Total cost: ${itinerary.total_cost.toLocaleString()}`);
  lines.push('');

  itinerary.days.forEach((day, i) => {
    lines.push(`Day ${i + 1} — ${fmtDate(day.date)}`);
    day.events.forEach(ev => {
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
  const safeName = itinerary.trip_summary.destination.replace(/[^a-z0-9]+/gi, '-').toLowerCase();

  const a = document.createElement('a');
  a.href = url;
  a.download = `waypoint-${safeName}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function copyLink() {
  const btn = document.getElementById('copyLinkBtn');
  try {
    await navigator.clipboard.writeText(window.location.href);
    const original = btn.textContent;
    btn.textContent = 'Link copied!';
    setTimeout(() => { btn.textContent = original; }, 1800);
  } catch (err) {
    alert('Could not copy the link automatically — you can copy it from the address bar.');
  }
}

async function init() {
  tripId = getTripId();
  if (!tripId) {
    document.body.innerHTML = '<div class="shell"><div class="submit-error" style="display:block;">No trip ID found in the URL.</div></div>';
    return;
  }

  try {
    const data = await apiRequest(`/trips/${tripId}/itinerary`);
    renderTripHeader(data.itinerary, data.budget_analysis, { showSuggestionCta: false });
    renderDays(data.itinerary);

    document.getElementById('downloadBtn').addEventListener('click', () => downloadItinerary(data.itinerary));
    document.getElementById('copyLinkBtn').addEventListener('click', copyLink);
  } catch (err) {
    document.getElementById('pageError').textContent = `Couldn't load your itinerary: ${err.message}`;
    document.getElementById('pageError').style.display = 'block';
  }
}

init();