// Trip form page logic only. Depends on app.js being loaded first
// (uses API_BASE, fmtDate, apiRequest).

document.querySelectorAll('#interestChips .chip').forEach(chip => {
  chip.addEventListener('click', () => chip.classList.toggle('selected'));
});

document.querySelectorAll('#carRentalGroup .radio-opt').forEach(opt => {
  opt.addEventListener('click', () => {
    document.querySelectorAll('#carRentalGroup .radio-opt').forEach(o => o.classList.remove('selected'));
    opt.classList.add('selected');
  });
});

function setInvalid(fieldId, invalid) {
  document.getElementById(fieldId).classList.toggle('invalid', invalid);
}

function validateAll() {
  let ok = true;
  let firstInvalid = null;

  const destination = document.getElementById('destination').value.trim();
  const destInvalid = !destination;
  setInvalid('f-destination', destInvalid);
  if (destInvalid) { ok = false; firstInvalid = firstInvalid || 'f-destination'; }

  const origin = document.getElementById('origin').value.trim();
  const originInvalid = !origin;
  setInvalid('f-origin', originInvalid);
  if (originInvalid) { ok = false; firstInvalid = firstInvalid || 'f-origin'; }

  const travelers = parseInt(document.getElementById('travelers').value, 10);
  const travelersInvalid = !travelers || travelers < 1;
  setInvalid('f-travelers', travelersInvalid);
  if (travelersInvalid) { ok = false; firstInvalid = firstInvalid || 'f-travelers'; }

  const start = document.getElementById('startDate').value;
  const end = document.getElementById('endDate').value;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const startDate = start ? new Date(start) : null;
  const startInvalid = !start || startDate < today;
  setInvalid('f-start', startInvalid);
  if (startInvalid) { ok = false; firstInvalid = firstInvalid || 'f-start'; }

  const endDate = end ? new Date(end) : null;
  const oneDayMs = 24 * 60 * 60 * 1000;
  const errEnd = document.querySelector('#f-end .error');

  let endInvalid = false;
  if (!end || !startDate) {
    endInvalid = true;
    errEnd.textContent = 'End date must be after the start date.';
  } else if (endDate <= startDate) {
    endInvalid = true;
    errEnd.textContent = 'End date must be after the start date.';
  } else if ((endDate - startDate) / oneDayMs > 6) {
    endInvalid = true;
    errEnd.textContent = 'Trips can be at most 7 days for now.';
  }

  setInvalid('f-end', endInvalid);
  if (endInvalid) { ok = false; firstInvalid = firstInvalid || 'f-end'; }

  const budget = parseFloat(document.getElementById('budget').value);
  const budgetInvalid = !budget || budget <= 0;
  setInvalid('f-budget', budgetInvalid);
  if (budgetInvalid) { ok = false; firstInvalid = firstInvalid || 'f-budget'; }

  if (!ok && firstInvalid) {
    document.getElementById(firstInvalid).scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  return ok;
}

function collectState() {
  const interests = Array.from(document.querySelectorAll('#interestChips .chip.selected'))
    .map(c => c.dataset.value);
  const carRental = document.querySelector('#carRentalGroup .radio-opt.selected').dataset.value === 'true';

  return {
    destination: document.getElementById('destination').value.trim(),
    origin_city: document.getElementById('origin').value.trim(),
    start_date: document.getElementById('startDate').value,
    end_date: document.getElementById('endDate').value,
    num_travelers: parseInt(document.getElementById('travelers').value, 10),
    budget: parseFloat(document.getElementById('budget').value),
    currency: 'INR', // Waypoint is India-only, domestic trips for v1 — no picker needed
    interests: interests,
    transport_pref: document.getElementById('transportPref').value,
    wants_rental_car: carRental,
    pace: document.getElementById('pace').value
  };
}

function goToReview() {
  if (!validateAll()) return;
  const s = collectState();

  document.getElementById('rv-destination').textContent = s.destination;
  document.getElementById('rv-origin').textContent = s.origin_city;
  document.getElementById('rv-dates').textContent = `${fmtDate(s.start_date)} — ${fmtDate(s.end_date)}`;
  document.getElementById('rv-travelers').textContent = s.num_travelers;
  document.getElementById('rv-interests').textContent = s.interests.length ? s.interests.join(', ') : 'None selected';
  document.getElementById('rv-transport').textContent = s.transport_pref;
  document.getElementById('rv-rental').textContent = s.wants_rental_car ? 'Yes' : 'No';
  document.getElementById('rv-pace').textContent = s.pace;
  document.getElementById('rv-budget').textContent = `₹${s.budget.toLocaleString('en-IN')}`;

  document.getElementById('formView').style.display = 'none';
  document.getElementById('reviewView').style.display = 'block';
  window.scrollTo(0, 0);
}

function backToForm() {
  document.getElementById('reviewView').style.display = 'none';
  document.getElementById('formView').style.display = 'block';
  window.scrollTo(0, 0);
}

// Browsers can restore this page from bfcache on Back/Forward navigation,
// preserving whatever inline display styles were left from goToReview()/
// backToForm(). Force a clean reset to the form view in that case.
window.addEventListener('pageshow', (event) => {
  if (event.persisted) {
    backToForm();
  }
});

async function submitTrip() {
  const btn = document.getElementById('submitBtn');
  const errBox = document.getElementById('submitError');
  errBox.style.display = 'none';
  btn.disabled = true;
  btn.textContent = 'Starting...';

  try {
    const payload = collectState();
    const data = await apiRequest('/trips', {
      method: 'POST',
      body: JSON.stringify(payload)
    });

    const tripId = data.trip_id || data.id;
    if (tripId) {
      window.location.href = `planning.html?trip_id=${tripId}`;
    } else {
      throw new Error('No trip_id returned from server.');
    }
  } catch (err) {
    errBox.textContent = `Couldn't start planning: ${err.message}`;
    errBox.style.display = 'block';
    btn.disabled = false;
    btn.innerHTML = 'Start planning <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
  }
}