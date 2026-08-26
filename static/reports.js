const reportsLayer = L.layerGroup();
const detailPanel = document.getElementById('detail-panel');
const detailContent = document.getElementById('detail-content');
const timelineSlider = document.getElementById('timeline-slider');
const timelineLabel = document.getElementById('timeline-label');

function markerColor(properties) {
  return properties.report_type === 'event' ? '#f87171' : '#38bdf8';
}

function formatTimestamp(iso) {
  const d = new Date(iso + 'Z');
  return d.toLocaleString();
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function reportDetailHtml(properties) {
  const lines = [];
  lines.push(`<h3>${properties.report_type === 'event' ? 'Event' : 'Quality report'}</h3>`);
  lines.push(`<div class="detail-timestamp">${formatTimestamp(properties.created_at)}</div>`);
  if (properties.obscured) {
    lines.push(`<div class="detail-location">${escapeHtml(properties.location_label)}</div>`);
  }
  if (properties.report_type === 'event') {
    lines.push(`<div>Type: ${escapeHtml(properties.event_subtype || 'unspecified')}</div>`);
    if (properties.ongoing) lines.push('<div>Still ongoing</div>');
  } else {
    ['taste', 'smell', 'color', 'pressure'].forEach((field) => {
      if (properties[field]) {
        lines.push(`<div>${field}: ${escapeHtml(properties[field])}</div>`);
      }
    });
  }
  if (properties.free_text) {
    lines.push(`<div class="detail-text">${escapeHtml(properties.free_text)}</div>`);
  }
  if (properties.photo_url) {
    lines.push(`<img src="${properties.photo_url}" alt="report photo" class="detail-photo" />`);
  }
  return lines.join('');
}

function renderReports(geojson) {
  if (!geojson || !Array.isArray(geojson.features)) return;
  reportsLayer.clearLayers();
  geojson.features.forEach((feature) => {
    if (!feature.geometry) return;
    const [lng, lat] = feature.geometry.coordinates;
    const marker = L.circleMarker([lat, lng], {
      radius: 8,
      color: markerColor(feature.properties),
      fillColor: markerColor(feature.properties),
      fillOpacity: 0.8,
      weight: 1,
    });
    marker.on('click', () => {
      if (window.mywaterCloseReportPanel) window.mywaterCloseReportPanel();
      detailContent.innerHTML = reportDetailHtml(feature.properties);
      detailPanel.classList.add('open');
    });
    marker.addTo(reportsLayer);
  });
}

function fetchReports(sinceDays) {
  let url = '/api/reports.geojson';
  if (sinceDays !== null) {
    const since = new Date(Date.now() - sinceDays * 24 * 60 * 60 * 1000);
    // Send the full ISO timestamp, not a bare YYYY-MM-DD date: the backend's
    // _parse_date_param normalizes any 10-character date-only string to
    // end-of-day (T23:59:59), which is correct for `until` (include the
    // whole day) but wrong for `since` — it would push the lower bound of
    // the lookback window to the end of today instead of N days ago at this
    // exact time, silently shrinking "last N days" toward minutes.
    url += `?since=${since.toISOString()}`;
  }
  return fetch(url)
    .then((r) => r.json())
    .then(renderReports)
    .catch((err) => {
      console.error(err);
      if (window.mywaterShowMessage) {
        window.mywaterShowMessage("Couldn't load the map data. Try refreshing the page.");
      }
    });
}

function closeDetailPanel() {
  detailPanel.classList.remove('open');
}

function timelineDays() {
  return Number(timelineSlider.value);
}

timelineSlider.addEventListener('input', () => {
  const days = timelineDays();
  timelineLabel.textContent = days >= 365 ? 'All time' : `Last ${days} day${days === 1 ? '' : 's'}`;
  fetchReports(days >= 365 ? null : days);
});

document.getElementById('detail-panel-close').addEventListener('click', closeDetailPanel);

reportsLayer.addTo(window.mywaterMap);
fetchReports(timelineDays());

window.mywaterRefreshReports = () => fetchReports(timelineDays());
window.mywaterCloseDetailPanel = closeDetailPanel;
