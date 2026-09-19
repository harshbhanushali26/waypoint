// frontend/js/map-render.js

let leafletMap = null;
let markersLayer = null;

const DAY_COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#14B8A6', '#6366F1'];

function initItineraryMap(containerId = 'mapContainer') {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (leafletMap) {
    setTimeout(() => { try { leafletMap.invalidateSize(); } catch (_) {} }, 100);
    return;
  }

  leafletMap = L.map(containerId).setView([20.5937, 78.9629], 5); // India center

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution: '© OpenStreetMap contributors'
  }).addTo(leafletMap);

  markersLayer = L.layerGroup().addTo(leafletMap);
}

function renderMapMarkers(itinerary) {
  if (!leafletMap || !markersLayer) return;
  markersLayer.clearLayers();

  const bounds = [];

  // 1. Hotel Marker
  const hotel = itinerary.chosen_hotel;
  if (hotel && hotel.latitude && hotel.longitude) {
    const lat = parseFloat(hotel.latitude);
    const lon = parseFloat(hotel.longitude);
    if (!isNaN(lat) && !isNaN(lon)) {
      bounds.push([lat, lon]);

      const safeName = (hotel.name || 'Hotel').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const checkinTime = (hotel.check_in_time || '14:00').replace(/</g, '&lt;').replace(/>/g, '&gt;');

      const hotelIcon = L.divIcon({
        className: 'custom-map-pin hotel-pin',
        html: `<div style="background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;padding:4px 10px;border-radius:999px;font-size:11px;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,0.5);white-space:nowrap;">🏨 ${safeName}</div>`,
        iconSize: [120, 28]
      });

      L.marker([lat, lon], { icon: hotelIcon })
        .bindPopup(`<b>${safeName}</b><br>Check-in: ${checkinTime}`)
        .addTo(markersLayer);
    }
  }

  // Set view to bounds if available
  if (bounds.length > 0) {
    leafletMap.fitBounds(bounds, { maxZoom: 14, padding: [40, 40] });
  }

  // Ensure map tiles redraw correctly after DOM layout stabilizes
  setTimeout(() => {
    try {
      if (leafletMap) leafletMap.invalidateSize();
    } catch (_) {}
  }, 250);
}   