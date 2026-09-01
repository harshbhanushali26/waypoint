// Shared between review.html and final.html. Depends on app.js (fmtDate).

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

const EVENT_ICONS = {
  transport: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h18M3 6h18M3 18h18"/></svg>',
  hotel_checkin: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18v-6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v6M3 18h18M7 10V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v4"/></svg>',
  hotel_checkout: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18v-6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v6M3 18h18M7 10V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v4"/></svg>',
  activity: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15 9 22 9 16.5 13.5 18.5 21 12 16.5 5.5 21 7.5 13.5 2 9 9 9 12 2"/></svg>'
};

function fmtEventType(type) {
  const map = {
    transport: 'Transport',
    hotel_checkin: 'Check-in',
    hotel_checkout: 'Check-out',
    activity: 'Activity'
  };
  return map[type] || type;
}

// opts.showSuggestionCta: true on review.html (points user to chat), false
// on final.html (no chat there, so just state the fact plainly).
function renderTripHeader(itinerary, budgetAnalysis, opts = {}) {
  const s = itinerary.trip_summary;
  document.getElementById('rv-title').textContent = s.destination;
  document.getElementById('rv-subtitle').textContent =
    `${fmtDate(s.start_date)} — ${fmtDate(s.end_date)} · ${s.num_travelers} traveler${s.num_travelers > 1 ? 's' : ''}`;
  document.getElementById('rv-cost').textContent = itinerary.total_cost.toLocaleString();

  const flag = document.getElementById('budgetFlag');
  if (!flag) return;

  if (budgetAnalysis && budgetAnalysis.over_budget) {
    flag.className = 'budget-flag over';
    let text = `Over budget by ${budgetAnalysis.overage_amount.toLocaleString()}.`;
    if (opts.showSuggestionCta) {
      text += budgetAnalysis.suggestions && budgetAnalysis.suggestions.length
        ? ' ' + budgetAnalysis.suggestions.join(' ')
        : ' Try asking to make it cheaper in the chat.';
    }
    flag.textContent = text;
    flag.style.display = 'block';
  } else if (budgetAnalysis) {
    flag.className = 'budget-flag ok';
    const hotel = itinerary.chosen_hotel;
    flag.textContent = hotel ? `Staying at ${hotel.name} · within budget.` : 'Within budget.';
    flag.style.display = 'block';
  } else {
    flag.style.display = 'none';
  }
}

function renderDays(itinerary, containerId = 'dayCards') {
  const container = document.getElementById(containerId);
  container.innerHTML = '';

  itinerary.days.forEach((day, i) => {
    const card = document.createElement('div');
    card.className = 'day-card';
    card.style.animationDelay = `${Math.min(i, 6) * 0.06}s`;

    const eventsHtml = day.events.map(ev => `
      <div class="event-row">
        <div class="event-tag ${ev.type === 'transport' ? 'transport' : ''}">
          ${EVENT_ICONS[ev.type] || ''}
          <span>${fmtEventType(ev.type)}</span>
        </div>
        <div class="event-body">
          <div class="event-time">${ev.time || ''}</div>
          <div class="event-title">${escapeHtml(ev.title)}</div>
          ${ev.details ? `<div class="event-details">${escapeHtml(ev.details)}</div>` : ''}
        </div>
      </div>
    `).join('');

    card.innerHTML = `
      <h3>Day ${i + 1}</h3>
      <div class="day-date">${fmtDate(day.date)}</div>
      ${eventsHtml}
    `;
    container.appendChild(card);
  });
}