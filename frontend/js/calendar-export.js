// frontend/js/calendar-export.js

function exportToICal(itinerary) {
  const summary = itinerary.trip_summary || {};
  let icsLines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Waypoint Travel Planner//EN',
    'CALSCALE:GREGORIAN',
    `X-WR-CALNAME:Trip to ${summary.destination || 'India'}`
  ];

  (itinerary.days || []).forEach(day => {
    const cleanDate = (day.date || '').replace(/-/g, '');
    (day.events || []).forEach((ev, idx) => {
      const timeStr = (ev.time || '10:00').replace(':', '') + '00';
      icsLines.push(
        'BEGIN:VEVENT',
        `UID:${cleanDate}-${idx}@waypoint.travel`,
        `DTSTART:${cleanDate}T${timeStr}`,
        `DTEND:${cleanDate}T${timeStr}`,
        `SUMMARY:[${ev.type.toUpperCase()}] ${ev.title}`,
        `DESCRIPTION:${ev.details || ''}`,
        'END:VEVENT'
      );
    });
  });

  icsLines.push('END:VCALENDAR');
  const blob = new Blob([icsLines.join('\r\n')], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `waypoint-${(summary.destination || 'trip').toLowerCase().replace(/\s+/g, '-')}.ics`;
  a.click();
  URL.revokeObjectURL(url);
}