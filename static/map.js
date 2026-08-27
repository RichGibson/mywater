const MYWATER_CENTER = [39.02, -122.62];
const MYWATER_ZOOM = 13;
const ADDRESS_LABEL_MIN_ZOOM = 15;
// Disabled: per-parcel tooltips are too slow with the live GeoJSON layer.
// Re-enable once addresses are baked into a pre-rendered tile set instead.
const ADDRESS_LABELS_ENABLED = false;

const map = L.map('map', { zoomControl: false }).setView(MYWATER_CENTER, MYWATER_ZOOM);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

let parcelsLayer = null;
let clustersLayer = null;
let selectedFeature = null;
let currentMode = 'exact';
let boundariesVisible = true;

function parcelStyle() {
  return { color: '#38bdf8', weight: 1, fillOpacity: 0.05 };
}

function clusterStyle(feature) {
  const safe = feature.properties.anonymization_safe;
  return {
    color: safe ? '#38bdf8' : '#8b949e',
    weight: 1,
    fillOpacity: safe ? 0.1 : 0.05,
    dashArray: safe ? null : '4 4',
  };
}

function onParcelClick(e) {
  const feature = e.target.feature;
  selectedFeature = {
    type: 'parcel',
    id: feature.properties.id,
    apn: feature.properties.apn,
    street_address: feature.properties.street_address,
  };
  window.mywaterOpenReportPanel(selectedFeature);
}

function onClusterClick(e) {
  const feature = e.target.feature;
  if (!feature.properties.anonymization_safe) {
    window.mywaterShowMessage(
      "This area doesn't have enough nearby homes to anonymize a report. Try a nearby area."
    );
    return;
  }
  selectedFeature = {
    type: 'cluster',
    id: feature.properties.id,
    streetName: feature.properties.street_name,
  };
  window.mywaterOpenReportPanel(selectedFeature);
}

function updateAddressLabelVisibility() {
  if (!ADDRESS_LABELS_ENABLED) return;
  const show = map.getZoom() >= ADDRESS_LABEL_MIN_ZOOM;
  map.getContainer().classList.toggle('hide-address-labels', !show);
}

function loadParcelsLayer() {
  return fetch('/api/parcels.geojson')
    .then((r) => r.json())
    .then((geojson) => {
      parcelsLayer = L.geoJSON(geojson, {
        style: parcelStyle,
        onEachFeature: (feature, layer) => {
          layer.on('click', onParcelClick);
          if (ADDRESS_LABELS_ENABLED && feature.properties.street_address) {
            layer.bindTooltip(feature.properties.street_address, {
              permanent: true,
              direction: 'center',
              className: 'address-label',
            });
          }
        },
      });
    });
}

function loadClustersLayer() {
  return fetch('/api/clusters.geojson')
    .then((r) => r.json())
    .then((geojson) => {
      clustersLayer = L.geoJSON(geojson, {
        style: clusterStyle,
        onEachFeature: (feature, layer) => {
          layer.on('click', onClusterClick);
        },
      });
    });
}

function updateControlLabel(checkbox) {
  const span = document.getElementById(checkbox.id + '-label');
  if (span) span.textContent = (checkbox.checked ? 'Hide ' : 'Show ') + checkbox.dataset.noun;
}
window.mywaterUpdateControlLabel = updateControlLabel;

function applyBoundariesVisibility() {
  const layer = currentMode === 'exact' ? parcelsLayer : clustersLayer;
  if (!layer) return;
  if (boundariesVisible) {
    if (!map.hasLayer(layer)) layer.addTo(map);
  } else if (map.hasLayer(layer)) {
    map.removeLayer(layer);
  }
}

function setMode(mode) {
  currentMode = mode;
  if (parcelsLayer && map.hasLayer(parcelsLayer)) map.removeLayer(parcelsLayer);
  if (clustersLayer && map.hasLayer(clustersLayer)) map.removeLayer(clustersLayer);
  applyBoundariesVisibility();

  document.getElementById('mode-exact').classList.toggle('active', mode === 'exact');
  document.getElementById('mode-obscure').classList.toggle('active', mode === 'obscure');
}

Promise.all([loadParcelsLayer(), loadClustersLayer()])
  .then(() => {
    setMode('exact');
    updateAddressLabelVisibility();
  })
  .catch((err) => {
    console.error(err);
    if (window.mywaterShowMessage) {
      window.mywaterShowMessage("Couldn't load the map data. Try refreshing the page.");
    }
  });

map.on('zoomend', updateAddressLabelVisibility);

const coordDisplay = document.getElementById('coord-display');
map.on('mousemove', (e) => {
  coordDisplay.textContent = `${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}`;
});

document.getElementById('mode-exact').addEventListener('click', () => setMode('exact'));
document.getElementById('mode-obscure').addEventListener('click', () => setMode('obscure'));

document.getElementById('control-boundaries').addEventListener('change', (e) => {
  boundariesVisible = e.target.checked;
  applyBoundariesVisibility();
  updateControlLabel(e.target);
});

window.mywaterMap = map;
