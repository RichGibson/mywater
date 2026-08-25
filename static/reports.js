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
    url += `?since=${since.toISOString().slice(0, 10)}`;
  }
  return fetch(url)
    .then((r) => r.json())
    .then(renderReports);
}

function timelineDays() {
  return Number(timelineSlider.value);
}

timelineSlider.addEventListener('input', () => {
  const days = timelineDays();
  timelineLabel.textContent = days >= 365 ? 'All time' : `Last ${days} day${days === 1 ? '' : 's'}`;
  fetchReports(days >= 365 ? null : days);
});

document.getElementById('detail-panel-close').addEventListener('click', () => {
  detailPanel.classList.remove('open');
});

reportsLayer.addTo(window.mywaterMap);
fetchReports(timelineDays());

window.mywaterRefreshReports = () => fetchReports(timelineDays());
