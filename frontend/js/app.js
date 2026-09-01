// Shared across every page. Page-specific logic lives in its own <page>.js file.

const API_BASE = window.__WAYPOINT_API_BASE__ || 'http://localhost:8000';

function fmtDate(d) {
  if (!d) return '';
  return new Date(d).toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' });
}

// Wraps fetch with JSON headers + consistent error handling.
// Throws an Error with the response body text on non-2xx so callers can
// show it directly in a .submit-error box.
async function apiRequest(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed (${res.status})`);
  }

  // Some endpoints (e.g. status polling) may return 204 with no body.
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return res.json();
  }
  return null;
}