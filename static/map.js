const MYWATER_CENTER = [39.02, -122.62];
const MYWATER_ZOOM = 13;

const map = L.map('map', { zoomControl: false }).setView(MYWATER_CENTER, MYWATER_ZOOM);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

let parcelsLayer = null;
let clustersLayer = null;
let selectedFeature = null;

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
  selectedFeature = { type: 'parcel', id: feature.properties.id, apn: feature.properties.apn };
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

function loadParcelsLayer() {
  return fetch('/api/parcels.geojson')
    .then((r) => r.json())
    .then((geojson) => {
      parcelsLayer = L.geoJSON(geojson, {
        style: parcelStyle,
        onEachFeature: (feature, layer) => {
          layer.on('click', onParcelClick);
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

function setMode(mode) {
  if (parcelsLayer && map.hasLayer(parcelsLayer)) map.removeLayer(parcelsLayer);
  if (clustersLayer && map.hasLayer(clustersLayer)) map.removeLayer(clustersLayer);
  if (mode === 'exact' && parcelsLayer) parcelsLayer.addTo(map);
  if (mode === 'obscure' && clustersLayer) clustersLayer.addTo(map);

  document.getElementById('mode-exact').classList.toggle('active', mode === 'exact');
  document.getElementById('mode-obscure').classList.toggle('active', mode === 'obscure');
}

Promise.all([loadParcelsLayer(), loadClustersLayer()])
  .then(() => {
    setMode('exact');
  })
  .catch((err) => {
    console.error(err);
    if (window.mywaterShowMessage) {
      window.mywaterShowMessage("Couldn't load the map data. Try refreshing the page.");
    }
  });

document.getElementById('mode-exact').addEventListener('click', () => setMode('exact'));
document.getElementById('mode-obscure').addEventListener('click', () => setMode('obscure'));

window.mywaterMap = map;
