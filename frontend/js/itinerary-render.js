// frontend/js/itinerary-render.js
// Shared between review.html and final.html. Depends on app.js (fmtDate).

function escapeHtml(str) {
  if (!str) return '';
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

// In-memory cache for Wikipedia images
const _wikiImageCache = {};

function isCleanPhoto(url) {
  if (!url) return false;
  const lower = url.toLowerCase();
  if (lower.endsWith('.svg.png') || lower.endsWith('.svg')) return false;
  if (lower.includes('map') || lower.includes('locator') || lower.includes('flag') || lower.includes('symbol') || lower.includes('logo') || lower.includes('icon')) {
    return false;
  }
  return true;
}

// Clean search using Wikipedia Action Query API (never returns 404s)
async function fetchWikiImage(query, destination = '') {
  if (!query) return null;

  // Clean noise words like "Tour", "Walk", or parenthetical notes
  const cleanTitle = query.replace(/\(.*?\)/g, '').replace(/Tour|Walk|Visit|Exploration/gi, '').trim();
  const cacheKey = cleanTitle.toLowerCase();
  
  if (_wikiImageCache[cacheKey] !== undefined) {
    return _wikiImageCache[cacheKey];
  }

  const destName = destination ? destination.split(',')[0].trim() : '';
  const searchQueries = destName
    ? [`${cleanTitle} ${destName}`, cleanTitle]
    : [cleanTitle];

  for (const q of searchQueries) {
    try {
      const url = `https://en.wikipedia.org/w/api.php?action=query&format=json&origin=*&generator=search&gsrsearch=${encodeURIComponent(q)}&gsrlimit=3&prop=pageimages&pithumbsize=400`;
      const res = await fetch(url);
      if (!res.ok) continue;

      const data = await res.json();
      const pages = data.query && data.query.pages ? Object.values(data.query.pages) : [];
      
      for (const page of pages) {
        const thumbUrl = page.thumbnail && page.thumbnail.source;
        if (thumbUrl && isCleanPhoto(thumbUrl)) {
          _wikiImageCache[cacheKey] = thumbUrl;
          return thumbUrl;
        }
      }
    } catch (err) {
      // Continue to next query fallback
    }
  }

  _wikiImageCache[cacheKey] = null;
  return null;
}

// Renders the trip title, dates, total cost, breakdown pills, and triggers Leaflet map
function renderTripHeader(itinerary, budgetAnalysis, opts = {}) {
  const s = itinerary.trip_summary;
  if (!s) return;

  const titleEl = document.getElementById('rv-title');
  if (titleEl) titleEl.textContent = s.destination;

  const subEl = document.getElementById('rv-subtitle');
  if (subEl) {
    subEl.textContent = `${fmtDate(s.start_date)} — ${fmtDate(s.end_date)} · ${s.num_travelers} traveler${s.num_travelers > 1 ? 's' : ''}`;
  }

  const costEl = document.getElementById('rv-cost');
  if (costEl) costEl.textContent = (itinerary.total_cost || 0).toLocaleString('en-IN');

  // Render cost breakdown pills in dedicated summary bar section
  renderCostBreakdown(itinerary, budgetAnalysis);

  // Initialize and render Leaflet Map markers automatically
  if (typeof initItineraryMap === 'function' && typeof renderMapMarkers === 'function') {
    initItineraryMap('mapContainer');
    renderMapMarkers(itinerary);
  }

  const flag = document.getElementById('budgetFlag');
  if (flag) {
    if (budgetAnalysis && budgetAnalysis.over_budget) {
      flag.className = 'budget-flag over';
      let text = `Over budget by ₹${(budgetAnalysis.overage_amount || 0).toLocaleString('en-IN')}.`;
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

  renderDataGaps(itinerary);
}

// Renders category cost breakdown pills
function renderCostBreakdown(itinerary, budgetAnalysis) {
  let costContainer = document.getElementById('costBreakdownBar');
  if (!costContainer) {
    const summaryBar = document.querySelector('.trip-summary-bar');
    if (!summaryBar) return;
    costContainer = document.createElement('div');
    costContainer.id = 'costBreakdownBar';
    costContainer.className = 'cost-breakdown-bar';
    const budgetFlag = document.getElementById('budgetFlag');
    if (budgetFlag) {
      summaryBar.insertBefore(costContainer, budgetFlag);
    } else {
      summaryBar.appendChild(costContainer);
    }
  }

  const breakdown = (budgetAnalysis && budgetAnalysis.cost_breakdown) || {};
  let flightsCost = Number(breakdown.flights) || 0;
  let trainsCost = Number(breakdown.trains) || 0;
  let hotelCost = Number(breakdown.hotels) || (itinerary.chosen_hotel && Number(itinerary.chosen_hotel.total_price)) || 0;
  let activitiesCost = Number(breakdown.activities) || 0;

  // Fallback for transport if missing from budget breakdown (e.g. static samples or raw itineraries)
  if (!flightsCost && !trainsCost && Array.isArray(itinerary.chosen_transport) && itinerary.chosen_transport.length > 0) {
    itinerary.chosen_transport.forEach(t => {
      const p = Number(t.price) || 0;
      if (t.mode === 'train') {
        trainsCost += p;
      } else {
        flightsCost += p;
      }
    });
  }

  const transportCost = flightsCost || trainsCost;
  const transportLabel = flightsCost ? '✈️ Flights' : (trainsCost ? '🚆 Trains' : '🚗 Transport');

  costContainer.innerHTML = `
    <div class="cost-pill">${transportLabel}: ₹${transportCost.toLocaleString('en-IN')}</div>
    <div class="cost-pill">🏨 Hotel: ₹${hotelCost.toLocaleString('en-IN')}</div>
    <div class="cost-pill">🎟️ Activities: ${activitiesCost > 0 ? '₹' + activitiesCost.toLocaleString('en-IN') : 'Included'}</div>
  `;
}

// Renders day-by-day schedule cards
function renderDays(itinerary, containerId = 'dayCards') {
  const container = document.getElementById(containerId);
  if (!container || !itinerary || !itinerary.days) return;
  container.innerHTML = '';

  const destination = (itinerary.trip_summary && itinerary.trip_summary.destination) || '';

  itinerary.days.forEach((day, i) => {
    const card = document.createElement('div');
    card.className = 'day-card';
    card.style.animationDelay = `${Math.min(i, 6) * 0.06}s`;

    const eventsHtml = day.events.map((ev, evIdx) => {
      const isActivity = ev.type === 'activity';
      const imgPlaceholderId = `img-day-${i}-ev-${evIdx}`;

      return `
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
          ${isActivity ? `
            <div class="place-photo-wrapper" id="${imgPlaceholderId}" style="display:none;">
              <img class="place-thumb-img" referrerpolicy="no-referrer" alt="${escapeHtml(ev.title)}" onerror="this.parentElement.style.display='none';">
            </div>
          ` : ''}
        </div>
      `;
    }).join('');

    card.innerHTML = `
      <h3>Day ${i + 1}</h3>
      <div class="day-date">${fmtDate(day.date)}</div>
      ${eventsHtml}
    `;
    container.appendChild(card);

    // Asynchronously fetch real photos for activities
    day.events.forEach(async (ev, evIdx) => {
      if (ev.type !== 'activity') return;
      const el = document.getElementById(`img-day-${i}-ev-${evIdx}`);
      if (!el) return;

      const imgUrl = await fetchWikiImage(ev.title, destination);
      if (imgUrl) {
        const img = el.querySelector('img');
        if (img) {
          img.src = imgUrl;
          el.style.display = 'block';
        }
      } else {
        el.style.display = 'none';
      }
    });
  });
}

function renderDataGaps(itinerary) {
  const el = document.getElementById('dataGapsNotice');
  if (!el) return;

  const gaps = itinerary.data_gaps;
  if (!gaps || gaps.length === 0) {
    el.style.display = 'none';
    return;
  }

  const text = gaps.length === 1
    ? gaps[0]
    : `Some live data was unavailable when this was built: ${gaps.join(' ')}`;

  el.innerHTML = `
    <span class="dgn-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v5M12 16h.01"/></svg></span>
    <span>${escapeHtml(text)}</span>
    <span class="dgn-close" title="Dismiss">✕</span>
  `;
  el.style.display = 'flex';

  el.querySelector('.dgn-close').addEventListener('click', () => {
    el.style.display = 'none';
  });
}