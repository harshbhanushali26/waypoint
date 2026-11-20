// frontend/js/itinerary-render.js
// Shared by review.html and final.html. Depends on app.js (fmtDate).

const RUPEE = n => '₹' + (Number(n) || 0).toLocaleString('en-IN');

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ── Icons ───────────────────────────────────────────────────────────────────

const svg = d => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;

const ICONS = {
  flight: svg('<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.5.9c-.3.5-.1 1.1.4 1.4L9 12l-2 3H4l-1 1.5 3 1 1 3L8.5 19l3-2 3.1 5.4c.3.5.9.7 1.4.4l.9-.5c.4-.2.6-.6.5-1.1z"/>'),
  train: svg('<rect x="5" y="3" width="14" height="14" rx="3"/><path d="M5 11h14M9 21l2-4M15 21l-2-4"/>'),
  hotel_checkin: svg('<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3"/>'),
  hotel_checkout: svg('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>'),
  activity: svg('<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>')
};

// Also used by final.js for the .txt export.
function fmtEventType(type) {
  const map = {
    transport: 'Transport',
    hotel_checkin: 'Check-in',
    hotel_checkout: 'Check-out',
    activity: 'Activity'
  };
  return map[type] || type;
}

// ── Time helpers (handle "08:15" and "2026-12-10 11:10") ────────────────────

function timePart(s) {
  const m = String(s || '').match(/(\d{1,2}):(\d{2})/);
  return m ? m[1].padStart(2, '0') + ':' + m[2] : '';
}

function datePart(s) {
  const m = String(s || '').match(/(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : '';
}

function minutesBetween(a, b) {
  const ta = timePart(a), tb = timePart(b);
  if (!ta || !tb) return null;
  const da = datePart(a), db = datePart(b);
  if (da && db) {
    const diff = Math.round((new Date(`${db}T${tb}:00`) - new Date(`${da}T${ta}:00`)) / 60000);
    return diff > 0 ? diff : null;
  }
  const toMin = t => parseInt(t.slice(0, 2), 10) * 60 + parseInt(t.slice(3), 10);
  let diff = toMin(tb) - toMin(ta);
  if (diff <= 0) diff += 1440;
  return diff;
}

function fmtDuration(min) {
  if (!min) return '';
  const h = Math.floor(min / 60), m = min % 60;
  return h ? (m ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
}

function fmtDay(d) {
  if (!d) return '';
  const dt = new Date(`${d}T00:00:00`);
  return isNaN(dt) ? d : dt.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
}

// ── Transport legs ──────────────────────────────────────────────────────────

function legEnd(leg, side) {
  const name = leg[`${side}_airport_name`] || leg[`${side}_station_name`] || leg[`${side}_station`] || '';
  let code = leg[`${side}_airport`] || leg[`${side}_station_code`] || '';
  if (!code) {
    const m = String(name).match(/\(([A-Z0-9]{2,5})\)/);
    if (m) code = m[1];
  }
  return { code };
}

// Match a transport event to a chosen_transport leg by time (and date if present).
function findLeg(itinerary, day, ev, used) {
  const legs = itinerary.chosen_transport || [];
  const t = timePart(ev.time);
  if (!t) return null;
  for (let i = 0; i < legs.length; i++) {
    if (used.has(i)) continue;
    const hit = [legs[i].departure_time, legs[i].arrival_time].some(x => {
      if (timePart(x) !== t) return false;
      const d = datePart(x);
      return !d || d === day.date;
    });
    if (hit) return { leg: legs[i], idx: i };
  }
  return null;
}

function legCardHtml(leg, travelers) {
  const from = legEnd(leg, 'departure'), to = legEnd(leg, 'arrival');
  if (!from.code || !to.code) return '';

  const dep = timePart(leg.departure_time), arr = timePart(leg.arrival_time);
  const dd = datePart(leg.departure_time), ad = datePart(leg.arrival_time);
  const nextDay = dd && ad && dd !== ad;
  const mins = minutesBetween(leg.departure_time, leg.arrival_time);

  const carrier = [
    leg.airline || leg.train_name || leg.operator,
    String(leg.flight_number || leg.train_number || leg.flight_id || '').replace(/^(outbound|return)-/, '')
  ].filter(Boolean).join(' ');

  const stops = leg.stops === 0 ? 'Non-stop' : (leg.stops > 0 ? `${leg.stops} stop${leg.stops > 1 ? 's' : ''}` : '');
  const price = Number(leg.price) > 0
    ? `<span><b>${RUPEE(leg.price)}</b>${travelers > 1 ? ` for ${travelers}` : ''}</span>` : '';

  const meta = [
    carrier ? `<span>${escapeHtml(carrier)}</span>` : '',
    mins ? `<span><b>${fmtDuration(mins)}</b></span>` : '',
    stops ? `<span>${stops}</span>` : '',
    price
  ].filter(Boolean).join('');

  return `
    <div class="leg-card">
      <div class="leg-route">
        <div class="leg-end"><span class="leg-code">${escapeHtml(from.code)}</span><span class="leg-time">${dep}</span></div>
        <div class="leg-line"></div>
        <div class="leg-end end"><span class="leg-code">${escapeHtml(to.code)}</span><span class="leg-time">${arr}${nextDay ? ' <small>+1</small>' : ''}</span></div>
      </div>
      ${meta ? `<div class="leg-meta">${meta}</div>` : ''}
    </div>`;
}

// ── Photos: accept a Wikipedia image only when the page title IS the place ──

const _wikiImageCache = {};
const IMG_BAD_TOKENS = new Set(['map', 'maps', 'locator', 'flag', 'flags', 'logo', 'icon', 'symbol', 'svg', 'emblem', 'coat', 'seal']);
const STOP_WORDS = new Set(['the', 'of', 'and', 'in', 'at', 'a', 'an', 'to', 'for']);

function isCleanPhoto(url) {
  if (!url) return false;
  let file = '';
  try { file = decodeURIComponent(url.split('/').pop() || ''); } catch (_) { file = url; }
  return !file.toLowerCase().split(/[^a-z0-9]+/).some(t => IMG_BAD_TOKENS.has(t));
}

function tokenize(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter(t => t && !STOP_WORDS.has(t));
}

// Every word of the Wikipedia title must appear in the activity name.
// "Anjuna Beach" matches "Anjuna Beach Sunset & Market"; "Emblem of India" doesn't match "Panaji City Center".
function titleMatches(pageTitle, query, destName) {
  const tt = tokenize(pageTitle), qt = new Set(tokenize(query));
  if (!tt.length) return false;
  if (tt.length === 1 && tt[0].length < 4) return false;
  if (destName && tokenize(destName).join(' ') === tt.join(' ')) return false;
  return tt.every(t => qt.has(t));
}

async function fetchWikiImage(query, destination = '') {
  if (!query) return null;

  const cleanTitle = query.replace(/\(.*?\)/g, '').trim();
  const destName = destination ? destination.split(',')[0].trim() : '';
  const cacheKey = `${cleanTitle.toLowerCase()}|${destName.toLowerCase()}`;
  if (_wikiImageCache[cacheKey] !== undefined) return _wikiImageCache[cacheKey];

  const searches = destName ? [`${cleanTitle} ${destName}`, cleanTitle] : [cleanTitle];

  for (const q of searches) {
    try {
      const url = `https://en.wikipedia.org/w/api.php?action=query&format=json&origin=*&generator=search&gsrsearch=${encodeURIComponent(q)}&gsrlimit=5&prop=pageimages&piprop=thumbnail&pithumbsize=400`;
      const res = await fetch(url);
      if (!res.ok) continue;
      const data = await res.json();
      const pages = data.query && data.query.pages
        ? Object.values(data.query.pages).sort((a, b) => (a.index || 0) - (b.index || 0))
        : [];

      for (const page of pages) {
        const thumb = page.thumbnail && page.thumbnail.source;
        if (thumb && isCleanPhoto(thumb) && titleMatches(page.title, cleanTitle, destName)) {
          _wikiImageCache[cacheKey] = thumb;
          return thumb;
        }
      }
    } catch (_) { /* try next query */ }
  }

  _wikiImageCache[cacheKey] = null;
  return null;
}

// ── Summary: title, total, cost bar, hotel strip, budget flag, map ──────────

function costParts(itinerary, budgetAnalysis) {
  const cb = itinerary.cost_breakdown || {};
  const legSum = (itinerary.chosen_transport || []).reduce((a, l) => a + (Number(l.price) || 0), 0);
  const hotel = itinerary.chosen_hotel;

  const transport = Number(cb.transport) || legSum;
  const stay = Number(cb.lodging) || (hotel && Number(hotel.total_price)) || 0;
  const activities = Number(cb.activities) || 0;
  const total = Number(itinerary.total_cost) || (transport + stay + activities);
  const budget = Number(budgetAnalysis && budgetAnalysis.budget) || 0;
  return { transport, stay, activities, total, budget };
}

function renderTripHeader(itinerary, budgetAnalysis, opts = {}) {
  const s = itinerary.trip_summary;
  if (!s) return;
  const parts = costParts(itinerary, budgetAnalysis);

  const titleEl = document.getElementById('rv-title');
  if (titleEl) titleEl.textContent = s.destination;

  const subEl = document.getElementById('rv-subtitle');
  if (subEl) {
    subEl.textContent = `${fmtDate(s.start_date)} — ${fmtDate(s.end_date)} · ${s.num_travelers} traveler${s.num_travelers > 1 ? 's' : ''}`;
  }

  const costEl = document.getElementById('rv-cost');
  if (costEl) costEl.textContent = parts.total.toLocaleString('en-IN');

  renderCostBreakdown(itinerary, budgetAnalysis);
  renderHotelStrip(itinerary);

  if (typeof initItineraryMap === 'function' && typeof renderMapMarkers === 'function') {
    initItineraryMap('mapContainer');
    renderMapMarkers(itinerary);
  }

  // The bar shows "within budget" on its own. The red flag appears only when over.
  const flag = document.getElementById('budgetFlag');
  if (flag) {
    if (budgetAnalysis && budgetAnalysis.over_budget) {
      flag.className = 'budget-flag over';
      let text = `Over budget by ${RUPEE(budgetAnalysis.overage_amount)}.`;
      if (opts.showSuggestionCta) {
        text += budgetAnalysis.suggestions && budgetAnalysis.suggestions.length
          ? ' ' + budgetAnalysis.suggestions.join(' ')
          : ' Ask for a cheaper plan in the chat.';
      }
      flag.textContent = text;
      flag.style.display = 'block';
    } else {
      flag.style.display = 'none';
    }
  }

  renderDataGaps(itinerary);
}

function renderCostBreakdown(itinerary, budgetAnalysis) {
  let el = document.getElementById('costBreakdownBar');
  if (!el) {
    const summaryBar = document.querySelector('.trip-summary-bar');
    if (!summaryBar) return;
    el = document.createElement('div');
    el.id = 'costBreakdownBar';
    el.className = 'cost-breakdown-bar';
    summaryBar.appendChild(el);
  }

  const p = costParts(itinerary, budgetAnalysis);
  const scale = Math.max(p.budget, p.total, 1);
  const pct = v => ((v / scale) * 100).toFixed(2);
  const over = p.budget > 0 && p.total > p.budget;
  const left = p.budget - p.total;

  const segs = [['transport', p.transport], ['stay', p.stay], ['activities', p.activities]]
    .filter(([, v]) => v > 0)
    .map(([k, v]) => `<span class="cost-seg ${k}" style="width:${pct(v)}%"></span>`).join('');
  const marker = over ? `<span class="cost-budget-marker" style="left:${pct(p.budget)}%"></span>` : '';

  const legend = [
    `<div class="cost-legend-item"><span class="cost-swatch transport"></span>Transport <b>${RUPEE(p.transport)}</b></div>`,
    `<div class="cost-legend-item"><span class="cost-swatch stay"></span>Stay <b>${RUPEE(p.stay)}</b></div>`,
    p.activities > 0
      ? `<div class="cost-legend-item"><span class="cost-swatch activities"></span>Activities <b>${RUPEE(p.activities)}</b></div>`
      : `<div class="cost-legend-item muted"><span class="cost-swatch activities"></span>Activities not priced</div>`,
    p.budget > 0
      ? (over
        ? `<div class="cost-legend-item over">Over budget by <b>${RUPEE(-left)}</b></div>`
        : `<div class="cost-legend-item"><span class="cost-swatch left"></span>Left of ${RUPEE(p.budget)} <b>${RUPEE(left)}</b></div>`)
      : ''
  ].join('');

  el.innerHTML = `
    <div class="cost-bar"><div class="cost-bar-track">${segs}</div>${marker}</div>
    <div class="cost-legend">${legend}</div>`;
}

function renderHotelStrip(itinerary) {
  const bar = document.getElementById('costBreakdownBar');
  if (!bar) return;
  let strip = document.getElementById('hotelStrip');
  const h = itinerary.chosen_hotel;
  if (!h) { if (strip) strip.remove(); return; }

  if (!strip) {
    strip = document.createElement('div');
    strip.id = 'hotelStrip';
    strip.className = 'hotel-strip';
    bar.insertAdjacentElement('afterend', strip);
  }

  const amenities = Array.isArray(h.amenities) && h.amenities.length
    ? `<div class="hotel-amenities">${h.amenities.map(a => `<span class="hotel-amenity">${escapeHtml(a)}</span>`).join('')}</div>` : '';

  strip.innerHTML = `
    <span class="hs-label">Stay</span>
    <span class="hs-name">${escapeHtml(h.name)}</span>
    ${h.rating ? `<span class="hs-rating">Rated ${escapeHtml(h.rating)}</span>` : ''}
    <span>${h.check_in_time ? `Check-in ${escapeHtml(h.check_in_time)}` : ''}${h.check_in_time && h.check_out_time ? ' · ' : ''}${h.check_out_time ? `Check-out ${escapeHtml(h.check_out_time)}` : ''}</span>
    ${amenities}`;
}

// ── Day cards ───────────────────────────────────────────────────────────────

function renderDays(itinerary, containerId = 'dayCards') {
  const container = document.getElementById(containerId);
  if (!container || !itinerary || !itinerary.days) return;
  container.innerHTML = '';

  const s = itinerary.trip_summary || {};
  const destination = s.destination || '';
  const travelers = s.num_travelers || 1;
  const usedLegs = new Set();

  itinerary.days.forEach((day, i) => {
    const events = day.events || [];

    const rows = events.map((ev, evIdx) => {
      const isTransport = ev.type === 'transport';
      const isActivity = ev.type === 'activity';
      const isStay = ev.type === 'hotel_checkin' || ev.type === 'hotel_checkout';

      let leg = null;
      if (isTransport) {
        const found = findLeg(itinerary, day, ev, usedLegs);
        if (found) { leg = found.leg; usedLegs.add(found.idx); }
      }

      const isTrain = leg && leg.mode === 'train';
      const kind = isTransport ? (leg ? (isTrain ? 'Train' : 'Flight') : 'Transport') : fmtEventType(ev.type);
      const iconKey = isTransport ? (isTrain ? 'train' : 'flight') : (ICONS[ev.type] ? ev.type : 'activity');
      const cls = isTransport ? 'is-transport' : (isStay ? 'is-stay' : 'is-activity');
      const photoId = `img-day-${i}-ev-${evIdx}`;
      const legHtml = leg ? legCardHtml(leg, travelers) : '';

      return `
        <div class="event-row ${cls}">
          <div class="event-time">${escapeHtml(timePart(ev.time) || ev.time || '')}</div>
          <div class="event-spine"><span class="event-node">${ICONS[iconKey]}</span></div>
          <div class="event-body">
            <div class="event-main">
              <div class="event-text">
                <div class="event-kind">${escapeHtml(kind)}</div>
                <div class="event-title">${escapeHtml(ev.title)}</div>
                ${legHtml}
                ${ev.details && !legHtml ? `<div class="event-details">${escapeHtml(ev.details)}</div>` : ''}
              </div>
              ${isActivity ? `
                <div class="place-photo-wrapper" id="${photoId}" style="display:none;">
                  <img class="place-thumb-img" referrerpolicy="no-referrer" alt="${escapeHtml(ev.title)}" onerror="this.parentElement.style.display='none';">
                </div>` : ''}
            </div>
          </div>
        </div>`;
    }).join('');

    const card = document.createElement('div');
    card.className = 'day-card';
    card.style.animationDelay = `${Math.min(i, 6) * 0.06}s`;
    card.innerHTML = `
      <div class="day-head">
        <h3>Day ${i + 1}</h3>
        <span class="day-date">${escapeHtml(fmtDay(day.date))}</span>
      </div>
      ${rows || '<p class="day-empty">Nothing planned for this day.</p>'}`;
    container.appendChild(card);

    events.forEach(async (ev, evIdx) => {
      if (ev.type !== 'activity') return;
      const el = document.getElementById(`img-day-${i}-ev-${evIdx}`);
      if (!el) return;
      const imgUrl = await fetchWikiImage(ev.title, destination);
      const img = el.querySelector('img');
      if (imgUrl && img) {
        img.src = imgUrl;
        el.style.display = 'block';
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
  el.querySelector('.dgn-close').addEventListener('click', () => { el.style.display = 'none'; });
}