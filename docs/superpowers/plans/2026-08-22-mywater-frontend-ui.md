# mywater Frontend UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the public-facing map, report-submission UI, timeline, and About/FAQ page for the mywater community water-quality reporting site — the third and final of three mywater components, consuming the already-built, already-merged backend API.

**Architecture:** Two server-rendered pages (`GET /`, the map; `GET /about`, static content) via FastAPI + Jinja2, following `projects/template-code`'s `base.html`/nav/footer/dark-theme convention. All interactivity is vanilla JS + Leaflet.js, talking to the existing JSON/GeoJSON API endpoints via plain `fetch()` — no HTMX (the backend returns JSON, not HTML fragments, so HTMX's core value doesn't apply here; see the design spec's 2026-08-22 revision). Three focused JS files: `map.js` (base map, parcel/cluster layers, mode toggle), `report-form.js` (submission side panel), `reports.js` (report markers, timeline, detail panel).

**Tech Stack:** FastAPI (Jinja2 templates, `StaticFiles`), vanilla JS (ES2017+, no build step), Leaflet.js 1.9.4 + OpenStreetMap tiles (both via CDN — this is a normal website, not a sandboxed Artifact, so CDN usage is standard and expected).

## Global Constraints

- No HTMX — plain `fetch()` for all API calls, per the spec's 2026-08-22 revision.
- Report submission via a slide-out side panel (desktop) / bottom-sheet or full-screen overlay (mobile) — not a modal, not a separate page.
- Timeline is a single "look back N days" slider, not a two-handle date range.
- Mobile/phone responsiveness is in scope for v1, not deferred.
- Visual theme matches `template-code`'s existing dark theme (`--bg: #0d1117`, `--accent: #38bdf8`, etc.) and nav/footer pattern — no new color scheme.
- Obscured reports must never show parcel-level identity in the UI — only the cluster's street label (`location_label` from the API), matching what the API already enforces server-side.
- Clicking a cluster where `anonymization_safe` is `false` must not open the report form — show an inert message instead, since the server would reject the submission anyway (400).
- Client-side form validation must mirror `models.ReportCreate`'s rules exactly (free-text ≤ 500 chars; quality reports need ≥1 rating or free text; event reports require `event_subtype`) so users get instant feedback, but the server remains the authoritative check.
- The About/FAQ page must explain the anonymization approach's actual limits (small clusters are excluded, not offered) — not a vague "your privacy is protected" claim.
- No raw lat/lng is ever sent from the client for a report submission — only `parcel_id` (exact) or `cluster_id` (obscured), matching the existing `POST /api/reports` contract exactly.
- Testing split (per spec): automated smoke tests for page routes (do they render, do they contain expected structural elements); everything visual/interactive (map clicks, panel behavior, timeline filtering, mobile layout) is manual — there is no browser-based test runner in this project.

---

## File Structure

```
projects/mywater/
  main.py                  -- MODIFY: mount static/templates, add GET /, GET /about, rename health check to GET /healthz
  templates/
    base.html               -- nav/footer, dark theme, per template-code convention
    index.html               -- the map page (built up across Tasks 1-4)
    about.html                -- About/FAQ content, complete in Task 1
  static/
    style.css                 -- base dark theme (copied from template-code) + map/panel/mobile overrides (built up across Tasks 1-4)
    map.js                     -- base map, parcels/clusters layers, mode toggle (Task 2)
    report-form.js               -- submission side panel (Task 3)
    reports.js                    -- report markers, timeline, detail panel (Task 4)
  tests/
    test_pages.py                  -- smoke tests for GET /, GET /about, GET /healthz
    test_db.py                      -- MODIFY: existing health-check test now targets /healthz
```

---

### Task 1: Page scaffolding — routes, base template, About/FAQ content

**Files:**
- Modify: `projects/mywater/main.py`
- Modify: `projects/mywater/tests/test_db.py`
- Create: `projects/mywater/templates/base.html`
- Create: `projects/mywater/templates/index.html`
- Create: `projects/mywater/templates/about.html`
- Create: `projects/mywater/static/style.css`
- Test: `projects/mywater/tests/test_pages.py`

**Interfaces:**
- Consumes: `tests/conftest.py`'s `client` fixture (already exists from the backend plan — provides a `TestClient` with isolated temp databases via `dependency_overrides`, importable with no changes needed).
- Produces: `GET /` (renders `index.html`), `GET /about` (renders `about.html`), `GET /healthz` (the former `GET /` health check, moved). Later tasks extend `index.html` and `style.css` in place — this task establishes their skeleton.

- [ ] **Step 1: Copy the base stylesheet**

`projects/mywater/static/style.css`:
```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:        #0d1117;
  --surface:   #161b22;
  --border:    #30363d;
  --text:      #e6edf3;
  --muted:     #8b949e;
  --accent:    #38bdf8;
  --accent-dim:#0ea5e9;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.6;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

nav {
  border-bottom: 1px solid var(--border);
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.85rem;
}

nav .site-name { font-weight: 700; color: var(--accent); font-size: 1rem; }
nav .site-name a { color: var(--accent); }

nav .siblings { display: flex; gap: 20px; }
nav .siblings a { color: var(--muted); }
nav .siblings a:hover { color: var(--text); text-decoration: none; }

main {
  max-width: 760px;
  margin: 0 auto;
  padding: 48px 24px 96px;
}

body.map-page main {
  max-width: none;
  margin: 0;
  padding: 0;
}

h1 {
  font-size: 2.4rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--accent);
  margin-bottom: 12px;
}

h2 {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent);
  margin: 32px 0 12px;
}

p { color: var(--muted); max-width: 580px; margin-bottom: 16px; }
p:last-child { margin-bottom: 0; }

blockquote {
  border-left: 2px solid var(--border);
  padding-left: 16px;
  margin: 0 0 16px;
  color: var(--muted);
  font-style: italic;
}

footer {
  border-top: 1px solid var(--border);
  padding: 24px;
  text-align: center;
  font-size: 0.8rem;
  display: flex;
  justify-content: center;
  gap: 24px;
  flex-wrap: wrap;
}

footer a { color: var(--border); }
footer a:hover { color: var(--muted); text-decoration: none; }
```

- [ ] **Step 2: Write base.html**

`projects/mywater/templates/base.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}mywater{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css" />
  {% block head %}{% endblock %}
</head>
<body class="{% block body_class %}{% endblock %}">

  <nav>
    <span class="site-name"><a href="/">mywater</a></span>
    <div class="siblings">
      <a href="/about">about</a>
      <a href="https://feedrater.com">feedrater</a>
      <a href="https://hellodrinkbot.com">drinkbot</a>
      <a href="https://laserloveandbeer.com">laserlove</a>
    </div>
  </nav>

  <main>
    {% block content %}{% endblock %}
  </main>

  <footer>
    <a href="/about">about</a>
    <a href="https://feedrater.com">feedrater</a>
    <a href="https://hellodrinkbot.com">drinkbot</a>
    <a href="https://laserloveandbeer.com">laserlove</a>
    <a href="https://github.com/RichGibson" target="_blank">github</a>
    <span style="color: var(--border);">Rich Gibson</span>
  </footer>

  {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 3: Write the index.html skeleton (extended in Tasks 2-4)**

`projects/mywater/templates/index.html`:
```html
{% extends "base.html" %}

{% block title %}mywater — Clearlake Oaks water reports{% endblock %}

{% block body_class %}map-page{% endblock %}

{% block head %}
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
{% endblock %}

{% block content %}
<div id="map"></div>
{% endblock %}

{% block scripts %}
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
{% endblock %}
```

- [ ] **Step 4: Write the About/FAQ page content**

`projects/mywater/templates/about.html`:
```html
{% extends "base.html" %}

{% block title %}About — mywater{% endblock %}

{% block content %}
<h1>About mywater</h1>
<p>
  mywater is a community-run map for residents of Clearlake Oaks (Lake County, CA) to
  report water quality issues — main breaks, outages, boil-water notices, and ongoing
  concerns about taste, smell, color, or pressure. It exists because reports were
  scattered across Facebook posts and hard to track over time; this site keeps a
  public, persistent record instead.
</p>

<h2>How location works</h2>
<p>
  When you file a report, you choose one of two ways to place it on the map:
</p>
<p>
  <strong>Show my exact location</strong> places your report at your specific parcel.
  Anyone viewing the map can see it's your property.
</p>
<p>
  <strong>Obscure my location</strong> places your report at the center of a small
  cluster of neighboring parcels (usually around 8) instead of your specific address.
  We never capture, transmit, or store your exact address for an obscured report —
  the map only ever shows you a cluster to choose from, not a point.
</p>

<h2>Limits of anonymization</h2>
<p>
  Obscuring your location works by grouping you with roughly 8 neighboring homes
  along the same street. In most of Clearlake Oaks, this genuinely hides which
  specific home a report came from. But on very short streets or in sparsely built
  areas, there may not be enough neighboring homes to form a group that size. When
  that happens, we don't offer that area as an anonymization option at all — you'll
  only see a cluster on the map if it has enough parcels nearby to actually protect
  your privacy.
</p>
<p>
  We also don't publish photos for obscured reports, since a phone photo can carry
  hidden location data (EXIF metadata) that would defeat the point of obscuring your
  address.
</p>
<p>
  If you need real anonymity, choose "obscure my location" and avoid including
  identifying details — like your house number — in your description.
</p>

<h2>Other things worth knowing</h2>
<p>
  Reports publish immediately with no review — there's no account system, and no
  moderation queue. This keeps the site simple, but it means reports reflect what
  residents submit, not a verified record. Submissions are rate-limited to prevent
  spam, but the limit is intentionally light.
</p>
{% endblock %}
```

- [ ] **Step 5: Write the failing tests for the new/moved routes**

`projects/mywater/tests/test_pages.py`:
```python
def test_index_page_renders_map_container(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert '<div id="map">' in resp.text


def test_about_page_renders_anonymization_explanation(client):
    resp = client.get("/about")
    assert resp.status_code == 200
    assert "obscure" in resp.text.lower()
    assert "anonymiz" in resp.text.lower()


def test_healthz_returns_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 6: Update the existing health-check test to target the new path**

In `projects/mywater/tests/test_db.py`, change `test_health_check_returns_ok` (the last function in the file) so it requests `/healthz` instead of `/`, since `main.py`'s Step 7 below moves the health check there:

```python
def test_health_check_returns_ok(tmp_path, monkeypatch):
    import db
    from fastapi.testclient import TestClient

    monkeypatch.setattr(db, "DEFAULT_APP_DB_PATH", tmp_path / "mywater_app.db")
    from main import app

    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_pages.py tests/test_db.py -v`
Expected: `test_pages.py`'s tests FAIL (404s, since `/`, `/about` aren't defined yet as page routes — `/` currently returns the health-check JSON, not HTML); `test_db.py::test_health_check_returns_ok` FAILS (404, since `/healthz` doesn't exist yet)

- [ ] **Step 8: Update main.py**

`projects/mywater/main.py` (replace entire file):
```python
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from db import init_app_db  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_app_db()
    yield


app = FastAPI(title="mywater", lifespan=lifespan)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

from routers import parcels, reports  # noqa: E402

app.include_router(reports.router, prefix="/api")
app.include_router(parcels.router, prefix="/api")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {})
```

Note: this uses the current (non-deprecated) `TemplateResponse(request, name, context)` signature — deliberately not the older `TemplateResponse(name, {"request": request})` form some older FastAPI examples use, since the older form emits a deprecation warning on current Starlette versions and this project has kept test output warning-free throughout.

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_pages.py tests/test_db.py -v`
Expected: PASS (3 tests in `test_pages.py`, all of `test_db.py` including the updated health check)

- [ ] **Step 10: Run the full suite to confirm no regressions**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/ -v`
Expected: PASS (all existing tests plus the 3 new ones, output pristine aside from the one pre-existing httpx/Starlette deprecation warning)

- [ ] **Step 11: Manual verification — start the dev server and load both pages**

```bash
cd projects/mywater
conda activate mywater
uvicorn main:app --reload --port 8765
```

In another terminal (or a browser, if available in your environment):
```bash
curl -s http://localhost:8765/ | grep -o '<div id="map">'
curl -s http://localhost:8765/about | grep -i "obscure"
curl -s http://localhost:8765/healthz
```
Expected: the first command prints the map div, the second prints lines containing "obscure", the third prints `{"status":"ok"}`. If you have a browser available, also open `http://localhost:8765/` and `http://localhost:8765/about` directly and confirm the nav/footer render with the dark theme and the About page's content is readable — this early check has nothing to verify visually yet beyond the shell working, but confirms the template/static wiring is correct before later tasks add real content to it.

- [ ] **Step 12: Commit**

```bash
git add projects/mywater/main.py projects/mywater/templates/ projects/mywater/static/style.css \
  projects/mywater/tests/test_pages.py projects/mywater/tests/test_db.py
git commit -m "mywater: page scaffolding, About/FAQ content, health check moved to /healthz"
```

---

### Task 2: Map initialization, parcel/cluster layers, mode toggle

**Files:**
- Modify: `projects/mywater/templates/index.html`
- Modify: `projects/mywater/static/style.css`
- Create: `projects/mywater/static/map.js`

**Interfaces:**
- Consumes: `GET /api/parcels.geojson` (FeatureCollection; each feature's `properties` has `id`, `apn`, `situsstr`, `cluster_id`, `centroid_lat`, `centroid_lng`), `GET /api/clusters.geojson` (FeatureCollection; each feature's `properties` has `id`, `street_name`, `centroid_lat`, `centroid_lng`, `parcel_count`, `anonymization_safe`).
- Produces (global, on `window`, for later tasks to call): `window.mywaterMap` (the Leaflet map instance), `window.mywaterGetSelectedFeature() -> {type: 'parcel'|'cluster', id: number, apn?: string, streetName?: string} | null`. Calls (but does not define) `window.mywaterOpenReportPanel(selection)` and `window.mywaterShowMessage(text)` — Task 3 defines these; since they're only invoked inside click handlers (never at page-load time), script load order relative to `report-form.js` doesn't matter as long as all `<script>` tags are present before a user can click anything, which they always will be.

- [ ] **Step 1: Add map UI markup to index.html**

Modify `projects/mywater/templates/index.html` — replace the `{% block content %}` block:
```html
{% block content %}
<div id="mode-toggle">
  <button id="mode-exact" class="mode-button active">Show my location</button>
  <button id="mode-obscure" class="mode-button">Obscure my location</button>
</div>
<div id="map"></div>
<div id="map-message"></div>
<div id="legend">
  <div class="legend-item"><span class="legend-swatch legend-event"></span> Event (break/outage)</div>
  <div class="legend-item"><span class="legend-swatch legend-quality"></span> Quality report</div>
</div>
{% endblock %}
```

And replace the `{% block scripts %}` block:
```html
{% block scripts %}
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="/static/map.js"></script>
{% endblock %}
```

- [ ] **Step 2: Write map.js**

`projects/mywater/static/map.js`:
```javascript
const MYWATER_CENTER = [39.02, -122.62];
const MYWATER_ZOOM = 13;

const map = L.map('map').setView(MYWATER_CENTER, MYWATER_ZOOM);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

let currentMode = 'exact'; // 'exact' | 'obscure'
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
  currentMode = mode;
  if (parcelsLayer && map.hasLayer(parcelsLayer)) map.removeLayer(parcelsLayer);
  if (clustersLayer && map.hasLayer(clustersLayer)) map.removeLayer(clustersLayer);
  if (mode === 'exact' && parcelsLayer) parcelsLayer.addTo(map);
  if (mode === 'obscure' && clustersLayer) clustersLayer.addTo(map);

  document.getElementById('mode-exact').classList.toggle('active', mode === 'exact');
  document.getElementById('mode-obscure').classList.toggle('active', mode === 'obscure');
}

Promise.all([loadParcelsLayer(), loadClustersLayer()]).then(() => {
  setMode('exact');
});

document.getElementById('mode-exact').addEventListener('click', () => setMode('exact'));
document.getElementById('mode-obscure').addEventListener('click', () => setMode('obscure'));

window.mywaterMap = map;
window.mywaterGetSelectedFeature = () => selectedFeature;
```

- [ ] **Step 3: Add map/mode-toggle/legend styling to style.css**

Append to `projects/mywater/static/style.css`:
```css
body.map-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

body.map-page nav,
body.map-page footer {
  flex: 0 0 auto;
}

body.map-page main {
  flex: 1 1 auto;
  position: relative;
  overflow: hidden;
}

#map {
  position: absolute;
  inset: 0;
}

#mode-toggle {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 1000;
  display: flex;
  gap: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px;
}

.mode-button {
  background: transparent;
  color: var(--muted);
  border: none;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 0.85rem;
  cursor: pointer;
}

.mode-button.active {
  background: var(--accent);
  color: var(--bg);
  font-weight: 700;
}

#map-message {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translate(-50%, 0);
  z-index: 1000;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 0.85rem;
  color: var(--text);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s;
}

#map-message.visible {
  opacity: 1;
}

#legend {
  position: absolute;
  bottom: 12px;
  right: 12px;
  z-index: 1000;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 0.8rem;
  color: var(--muted);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.legend-item:last-child {
  margin-bottom: 0;
}

.legend-swatch {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.legend-event { background: #f87171; }
.legend-quality { background: #38bdf8; }

@media (max-width: 600px) {
  #legend {
    font-size: 0.7rem;
    padding: 8px 10px;
  }

  .mode-button {
    padding: 8px 10px;
    font-size: 0.75rem;
  }
}
```

- [ ] **Step 4: Manual verification**

```bash
cd projects/mywater
conda activate mywater
uvicorn main:app --reload --port 8765
```

If you have browser automation tools available in this environment, use them to open `http://localhost:8765/`, confirm:
- The map loads centered on Clearlake Oaks with OpenStreetMap tiles visible
- Parcel outlines are visible when "Show my location" is active (the default)
- Clicking "Obscure my location" swaps to cluster outlines, with unsafe clusters visually distinct (dashed/gray) from safe ones
- Clicking a parcel or a safe cluster doesn't error in the browser console (it will currently do nothing visible, since `window.mywaterOpenReportPanel` isn't defined until Task 3 — check the console for a "not a function" error to confirm the click handler fired correctly and is just waiting on Task 3, not silently failing for some other reason)
- Clicking an unsafe cluster shows the "doesn't have enough nearby homes" message

If browser automation isn't available: verify via `curl -s http://localhost:8765/static/map.js | head -5` that the file is served correctly, verify `curl -s http://localhost:8765/api/parcels.geojson | python3 -m json.tool | head -20` and the equivalent for `clusters.geojson` return valid GeoJSON with real data (confirms the endpoints map.js depends on actually work end-to-end against the real `mywater.db`), and carefully re-read `map.js` for correctness rather than skipping verification — note in your report that full interactive/visual verification wasn't possible in this environment.

- [ ] **Step 5: Commit**

```bash
git add projects/mywater/templates/index.html projects/mywater/static/map.js projects/mywater/static/style.css
git commit -m "mywater: map initialization, parcel/cluster layers, mode toggle"
```

---

### Task 3: Report submission side panel

**Files:**
- Modify: `projects/mywater/templates/index.html`
- Modify: `projects/mywater/static/style.css`
- Create: `projects/mywater/static/report-form.js`

**Interfaces:**
- Consumes: `window.mywaterGetSelectedFeature`, `window.mywaterMap` (Task 2). Posts to `POST /api/reports` (multipart form: `report_type`, `obscured` ("true"/"false"), `parcel_id` or `cluster_id`, `free_text`, `taste`/`smell`/`color`/`pressure`, `event_subtype`, `ongoing`, `photo` file) — exact field names and validation rules from `projects/mywater/models.py`'s `ReportCreate` (already built, do not modify).
- Produces: `window.mywaterOpenReportPanel(selection)` (called by Task 2's click handlers; `selection` is `{type: 'parcel', id, apn}` or `{type: 'cluster', id, streetName}`), `window.mywaterShowMessage(text)` (called by Task 2 for the unsafe-cluster message). Calls (but does not define) `window.mywaterRefreshReports()` — Task 4 defines this, called only after a successful submission, which never happens at page-load time, so load order is safe the same way it was in Task 2.

- [ ] **Step 1: Add the side panel markup to index.html**

Modify `projects/mywater/templates/index.html` — add this inside `{% block content %}`, after the `#map` div and before `#legend` (or after `#legend`, position in the DOM doesn't matter since it's absolutely positioned):
```html
<div id="report-panel">
  <div id="report-panel-header">
    <span id="report-panel-location"></span>
    <button id="report-panel-close" type="button" aria-label="Close">&times;</button>
  </div>
  <form id="report-form">
    <input type="hidden" id="field-parcel-id" name="parcel_id" />
    <input type="hidden" id="field-cluster-id" name="cluster_id" />
    <input type="hidden" id="field-obscured" name="obscured" />

    <label for="field-report-type">Report type</label>
    <select id="field-report-type" name="report_type">
      <option value="quality">Ongoing quality issue</option>
      <option value="event">One-time event</option>
    </select>

    <div class="field-event">
      <label for="field-event-subtype">What kind of event?</label>
      <select id="field-event-subtype" name="event_subtype">
        <option value="main_break">Water main break</option>
        <option value="outage">Outage</option>
        <option value="boil_notice">Boil-water notice</option>
        <option value="other">Other</option>
      </select>
      <label>
        <input type="checkbox" id="field-ongoing" name="ongoing" value="true" />
        Still ongoing
      </label>
    </div>

    <div class="field-quality">
      <label for="field-taste">Taste</label>
      <select id="field-taste" name="taste">
        <option value="">No opinion</option>
        <option value="good">Good</option>
        <option value="off">Off</option>
        <option value="bad">Bad</option>
      </select>
      <label for="field-smell">Smell</label>
      <select id="field-smell" name="smell">
        <option value="">No opinion</option>
        <option value="good">Good</option>
        <option value="off">Off</option>
        <option value="bad">Bad</option>
      </select>
      <label for="field-color">Color</label>
      <select id="field-color" name="color">
        <option value="">No opinion</option>
        <option value="good">Good</option>
        <option value="off">Off</option>
        <option value="bad">Bad</option>
      </select>
      <label for="field-pressure">Pressure</label>
      <select id="field-pressure" name="pressure">
        <option value="">No opinion</option>
        <option value="good">Good</option>
        <option value="off">Off</option>
        <option value="bad">Bad</option>
      </select>
    </div>

    <label for="field-free-text">Description (optional, 500 characters max)</label>
    <textarea id="field-free-text" name="free_text" maxlength="500"></textarea>

    <label for="field-photo">Photo (optional, JPEG/PNG/HEIC, up to 5MB)</label>
    <input type="file" id="field-photo" name="photo" accept="image/jpeg,image/png,image/heic" />

    <div id="report-panel-error"></div>

    <button type="submit">Submit report</button>
  </form>
</div>
```

- [ ] **Step 2: Write report-form.js**

`projects/mywater/static/report-form.js`:
```javascript
const VALID_QUALITY_RATINGS = ['good', 'off', 'bad'];
const VALID_EVENT_SUBTYPES = ['main_break', 'outage', 'boil_notice', 'other'];
const FREE_TEXT_MAX_LENGTH = 500;
const MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024;
const ALLOWED_PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/heic'];

const panel = document.getElementById('report-panel');
const form = document.getElementById('report-form');
const panelError = document.getElementById('report-panel-error');
const messageBox = document.getElementById('map-message');

function showMessage(text) {
  messageBox.textContent = text;
  messageBox.classList.add('visible');
  setTimeout(() => messageBox.classList.remove('visible'), 4000);
}

function updateFieldVisibility() {
  const reportType = document.getElementById('field-report-type').value;
  document.querySelectorAll('.field-quality').forEach((el) => {
    el.style.display = reportType === 'quality' ? '' : 'none';
  });
  document.querySelectorAll('.field-event').forEach((el) => {
    el.style.display = reportType === 'event' ? '' : 'none';
  });
}

function openReportPanel(selection) {
  panelError.textContent = '';
  form.reset();
  document.getElementById('field-parcel-id').value = selection.type === 'parcel' ? selection.id : '';
  document.getElementById('field-cluster-id').value = selection.type === 'cluster' ? selection.id : '';
  document.getElementById('field-obscured').value = selection.type === 'cluster' ? 'true' : 'false';
  const label = selection.type === 'parcel'
    ? `Reporting for parcel ${selection.apn}`
    : `Reporting for the area near ${selection.streetName} (anonymized)`;
  document.getElementById('report-panel-location').textContent = label;
  updateFieldVisibility();
  panel.classList.add('open');
}

function closeReportPanel() {
  panel.classList.remove('open');
}

function validateForm(formData) {
  const reportType = formData.get('report_type');
  const freeText = formData.get('free_text') || '';
  if (freeText.length > FREE_TEXT_MAX_LENGTH) {
    return `Description must be at most ${FREE_TEXT_MAX_LENGTH} characters.`;
  }
  if (reportType === 'event') {
    const eventSubtype = formData.get('event_subtype');
    if (!eventSubtype || !VALID_EVENT_SUBTYPES.includes(eventSubtype)) {
      return 'Please choose what kind of event this is.';
    }
  } else if (reportType === 'quality') {
    const taste = formData.get('taste');
    const smell = formData.get('smell');
    const color = formData.get('color');
    const pressure = formData.get('pressure');
    const hasRating = [taste, smell, color, pressure].some(
      (v) => v && VALID_QUALITY_RATINGS.includes(v)
    );
    if (!hasRating && !freeText.trim()) {
      return 'Please rate at least one thing (taste, smell, color, pressure) or describe the issue.';
    }
  }
  const photo = formData.get('photo');
  if (photo && photo.size > 0) {
    if (!ALLOWED_PHOTO_TYPES.includes(photo.type)) {
      return 'Photo must be a JPEG, PNG, or HEIC image.';
    }
    if (photo.size > MAX_PHOTO_SIZE_BYTES) {
      return 'Photo must be smaller than 5MB.';
    }
  }
  return null;
}

function stripEmptyOptionalFields(formData) {
  // Empty <select> values ("No opinion") and an empty file input still show
  // up as empty-string/empty-file FormData entries; the backend's Pydantic
  // model treats an empty string as "set to empty string", not "unset", for
  // fields like taste/smell/color/pressure/event_subtype — so send them only
  // when the user actually picked something.
  ['taste', 'smell', 'color', 'pressure', 'event_subtype', 'free_text'].forEach((key) => {
    if (formData.get(key) === '') formData.delete(key);
  });
  const photo = formData.get('photo');
  if (photo && photo.size === 0) formData.delete('photo');
  if (formData.get('report_type') === 'quality') {
    formData.delete('event_subtype');
    formData.delete('ongoing');
  }
  if (formData.get('report_type') === 'event') {
    ['taste', 'smell', 'color', 'pressure'].forEach((key) => formData.delete(key));
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  panelError.textContent = '';

  const formData = new FormData(form);
  const clientError = validateForm(formData);
  if (clientError) {
    panelError.textContent = clientError;
    return;
  }
  stripEmptyOptionalFields(formData);

  const submitButton = form.querySelector('button[type="submit"]');
  submitButton.disabled = true;

  try {
    const resp = await fetch('/api/reports', {
      method: 'POST',
      body: formData,
    });
    if (resp.ok) {
      closeReportPanel();
      showMessage('Thanks — your report has been posted.');
      if (window.mywaterRefreshReports) window.mywaterRefreshReports();
    } else {
      const body = await resp.json().catch(() => ({}));
      panelError.textContent = body.detail || 'Something went wrong submitting your report. Please try again.';
    }
  } catch (err) {
    panelError.textContent = 'Could not reach the server. Check your connection and try again.';
  } finally {
    submitButton.disabled = false;
  }
});

document.getElementById('field-report-type').addEventListener('change', updateFieldVisibility);
document.getElementById('report-panel-close').addEventListener('click', closeReportPanel);

window.mywaterOpenReportPanel = openReportPanel;
window.mywaterShowMessage = showMessage;
```

Note on `stripEmptyOptionalFields`: the HTML `<select>` elements for `taste`/`smell`/`color`/`pressure`/`event_subtype` include a blank `""` option so users can leave a field unanswered — but `FormData` sends that as the literal string `""`, and FastAPI's `Optional[str] = Form(None)` parameter only defaults to `None` when the field is *absent* from the request, not when it's present-but-empty. Sending `taste=""` would reach `ReportCreate`'s validator as `""`, which fails the `VALID_QUALITY_RATINGS` check (empty string isn't `"good"`/`"off"`/`"bad"`) with a 422 — even though the user correctly left it blank. Deleting empty-string fields from the `FormData` before sending fixes this. The report-type-specific deletions (dropping quality fields from an event submission and vice versa) exist for the same reason: the hidden `<div class="field-quality">`/`<div class="field-event">` sections still have form elements in the DOM even when hidden via CSS, and hidden form elements are still included in `FormData`.

- [ ] **Step 3: Add side panel styling (desktop slide-out, mobile bottom sheet)**

Append to `projects/mywater/static/style.css`:
```css
#report-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 360px;
  max-width: 100%;
  background: var(--surface);
  border-left: 1px solid var(--border);
  transform: translateX(100%);
  transition: transform 0.2s ease-out;
  z-index: 1100;
  overflow-y: auto;
  padding: 16px;
}

#report-panel.open {
  transform: translateX(0);
}

#report-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

#report-panel-location {
  font-size: 0.9rem;
  color: var(--text);
  font-weight: 700;
}

#report-panel-close {
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 1.4rem;
  cursor: pointer;
  line-height: 1;
}

#report-form label {
  display: block;
  font-size: 0.8rem;
  color: var(--muted);
  margin: 12px 0 4px;
}

#report-form select,
#report-form textarea,
#report-form input[type="file"] {
  width: 100%;
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  font-size: 0.85rem;
  font-family: inherit;
}

#report-form textarea {
  min-height: 80px;
  resize: vertical;
}

#report-form button[type="submit"] {
  margin-top: 16px;
  width: 100%;
  background: var(--accent);
  color: var(--bg);
  border: none;
  border-radius: 6px;
  padding: 10px;
  font-weight: 700;
  font-size: 0.9rem;
  cursor: pointer;
}

#report-form button[type="submit"]:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

#report-panel-error {
  color: #f87171;
  font-size: 0.8rem;
  margin-top: 12px;
  min-height: 1em;
}

@media (max-width: 600px) {
  #report-panel {
    top: auto;
    left: 0;
    right: 0;
    width: auto;
    max-height: 80vh;
    border-left: none;
    border-top: 1px solid var(--border);
    border-radius: 12px 12px 0 0;
    transform: translateY(100%);
  }

  #report-panel.open {
    transform: translateY(0);
  }
}
```

- [ ] **Step 4: Manual verification**

```bash
cd projects/mywater
conda activate mywater
uvicorn main:app --reload --port 8765
```

If browser automation is available: open `http://localhost:8765/`, click a parcel, confirm the side panel slides in from the right with the correct location label, switch between "Ongoing quality issue" and "One-time event" and confirm the right fields show/hide, submit a quality report with just a taste rating (no text) and confirm it succeeds (watch the network tab or server logs for a 200 from `POST /api/reports`), then try submitting a quality report with nothing filled in at all and confirm the client-side validation message appears without a network request being made. Resize the browser to a narrow (mobile) width and confirm the panel becomes a bottom sheet.

If browser automation isn't available: verify the endpoint directly with `curl`:
```bash
curl -s -X POST http://localhost:8765/api/reports \
  -F "report_type=quality" -F "obscured=false" -F "parcel_id=1" -F "taste=bad"
```
(Replace `parcel_id=1` with a real parcel ID from `curl -s http://localhost:8765/api/parcels.geojson | python3 -c "import json,sys; print(json.load(sys.stdin)['features'][0]['properties']['id'])"` if `1` doesn't exist in your local `mywater.db`.) Confirm a 200 response with an `id` in the JSON body. Then re-read `report-form.js` carefully to confirm the client-side validation logic in `validateForm` matches `models.py`'s server-side rules exactly, and note in your report that full interactive/visual verification wasn't possible in this environment.

- [ ] **Step 5: Commit**

```bash
git add projects/mywater/templates/index.html projects/mywater/static/report-form.js projects/mywater/static/style.css
git commit -m "mywater: report submission side panel"
```

---

### Task 4: Report markers, timeline slider, detail panel

**Files:**
- Modify: `projects/mywater/templates/index.html`
- Modify: `projects/mywater/static/style.css`
- Create: `projects/mywater/static/reports.js`

**Interfaces:**
- Consumes: `window.mywaterMap` (Task 2). Fetches `GET /api/reports.geojson?since=...` (FeatureCollection; each feature's `properties` has `id`, `report_type`, `obscured`, `created_at`, `free_text`, `photo_url`, `taste`/`smell`/`color`/`pressure`, `event_subtype`, `ongoing`, and `location_label` only when `obscured` is `true`; `geometry` is a `Point` or `null`).
- Produces: `window.mywaterRefreshReports()` (called by Task 3 after a successful submission). This is the last task that adds new global functions — nothing after this depends on new globals.

- [ ] **Step 1: Add timeline and detail panel markup to index.html**

Modify `projects/mywater/templates/index.html` — add this inside `{% block content %}`, after `#report-panel`:
```html
<div id="timeline">
  <label for="timeline-slider" id="timeline-label">Last 90 days</label>
  <input type="range" id="timeline-slider" min="1" max="365" value="90" />
</div>

<div id="detail-panel">
  <button id="detail-panel-close" type="button" aria-label="Close">&times;</button>
  <div id="detail-content"></div>
</div>
```

- [ ] **Step 2: Add the reports.js script tag**

Modify `projects/mywater/templates/index.html`'s `{% block scripts %}` to add `reports.js` after `map.js`:
```html
{% block scripts %}
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="/static/map.js"></script>
<script src="/static/reports.js"></script>
<script src="/static/report-form.js"></script>
{% endblock %}
```

(`reports.js` runs before `report-form.js` because it needs `window.mywaterMap` to exist at load time — set by `map.js`, which already runs first — while `report-form.js`'s references to `window.mywaterRefreshReports` only happen inside a later `fetch` callback, not at load time, so its position relative to `reports.js` doesn't matter.)

- [ ] **Step 3: Write reports.js**

`projects/mywater/static/reports.js`:
```javascript
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
```

- [ ] **Step 4: Add timeline and detail panel styling**

Append to `projects/mywater/static/style.css`:
```css
#timeline {
  position: absolute;
  bottom: 12px;
  left: 12px;
  z-index: 1000;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 0.8rem;
  color: var(--muted);
  width: 220px;
}

#timeline-label {
  display: block;
  margin-bottom: 6px;
}

#timeline-slider {
  width: 100%;
}

#detail-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 320px;
  max-width: 100%;
  background: var(--surface);
  border-left: 1px solid var(--border);
  transform: translateX(100%);
  transition: transform 0.2s ease-out;
  z-index: 1100;
  overflow-y: auto;
  padding: 16px;
}

#detail-panel.open {
  transform: translateX(0);
}

#detail-panel-close {
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 1.4rem;
  cursor: pointer;
  line-height: 1;
  float: right;
}

#detail-content h3 {
  color: var(--accent);
  margin-bottom: 8px;
}

#detail-content .detail-timestamp {
  font-size: 0.8rem;
  color: var(--muted);
  margin-bottom: 8px;
}

#detail-content .detail-location {
  font-style: italic;
  margin-bottom: 8px;
}

#detail-content .detail-text {
  margin-top: 8px;
}

#detail-content .detail-photo {
  width: 100%;
  border-radius: 6px;
  margin-top: 12px;
}

@media (max-width: 600px) {
  #timeline {
    width: auto;
    left: 12px;
    right: 12px;
  }

  #detail-panel {
    top: auto;
    left: 0;
    right: 0;
    width: auto;
    max-height: 80vh;
    border-left: none;
    border-top: 1px solid var(--border);
    border-radius: 12px 12px 0 0;
    transform: translateY(100%);
  }

  #detail-panel.open {
    transform: translateY(0);
  }
}
```

- [ ] **Step 5: Manual verification**

```bash
cd projects/mywater
conda activate mywater
uvicorn main:app --reload --port 8765
```

If browser automation is available: submit a couple of test reports via the panel (from Task 3's verification), confirm both appear on the map as colored dots (red for event, blue for quality), click a marker and confirm the detail panel shows the right fields — for an obscured report, confirm it shows the street-area label and never a parcel address, and confirm no photo appears even if you attached one. Drag the timeline slider down to a small number of days and confirm markers disappear if your test reports are excluded by the window (they won't be, since you just created them — instead verify the label text updates correctly and the network tab shows a new `since=` request on each drag). Resize to mobile width and confirm the timeline control and detail panel remain usable.

If browser automation isn't available: use `curl` to submit 1-2 reports (as in Task 3's fallback verification, mixing `obscured=true` with a real safe `cluster_id` from `/api/clusters.geojson` and `obscured=false`), then `curl -s "http://localhost:8765/api/reports.geojson" | python3 -m json.tool` and manually confirm: the obscured report's properties have no `parcel_id`/`apn`/`cluster_id` keys and do have `location_label`; the non-obscured report's `geometry.coordinates` matches a real parcel centroid. Re-read `reports.js` to confirm `reportDetailHtml` never reads a field that isn't in this properties shape, and note in your report that full interactive/visual verification wasn't possible in this environment.

- [ ] **Step 6: Run the full backend test suite to confirm nothing broke**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/ -v`
Expected: PASS (all tests, output pristine aside from the one pre-existing warning) — this task doesn't touch any Python files, but confirms the manual `curl` exercises above didn't reveal a real backend regression.

- [ ] **Step 7: Commit**

```bash
git add projects/mywater/templates/index.html projects/mywater/static/reports.js projects/mywater/static/style.css
git commit -m "mywater: report markers, timeline slider, detail panel"
```

---

## Self-Review Notes

- **Spec coverage**: Overview & Scope's core capabilities (click to file a report, exact or obscured, two report types, optional photo, public map + timeline, no login) — Tasks 2-4. Anonymization guarantee and its limits, including the About/FAQ requirement — Task 1's `about.html` and Task 2's unsafe-cluster message. Report Submission Flow's side-panel pattern — Task 3. Map & Timeline UI's simplified single-slider timeline, mobile responsiveness, legend — Tasks 2 and 4. Error Handling's "click where no parcel/cluster exists" (Task 2, simply no click handler fires there since only real GeoJSON features are clickable — matches the spec's post-self-review correction that there's no boundary check to fail) and "malformed/missing required fields" (Task 3's client-side validation plus the existing server-side 422). Testing split (automated for routes, manual for interactivity) — Task 1's `test_pages.py` plus every task's manual verification step.
- **Placeholder scan**: none found — every step has complete code or a concrete shell/curl command.
- **Type consistency**: `window.mywaterOpenReportPanel`, `window.mywaterShowMessage`, `window.mywaterMap`, `window.mywaterGetSelectedFeature`, `window.mywaterRefreshReports` are defined exactly once each (in the task that owns them) and consumed with matching names/shapes in every task that calls them — verified by re-reading each task's Interfaces block against the others. Form field names in Task 3's HTML (`report_type`, `obscured`, `parcel_id`, `cluster_id`, `free_text`, `taste`, `smell`, `color`, `pressure`, `event_subtype`, `ongoing`, `photo`) match `routers/reports.py`'s actual `Form(...)` parameter names exactly (checked against the current file, not assumed). GeoJSON property names consumed in `map.js`/`reports.js` (`apn`, `street_name`, `anonymization_safe`, `report_type`, `obscured`, `location_label`, etc.) match `routers/parcels.py`/`routers/reports.py`'s actual response shapes exactly (checked against the current files, not assumed from the spec alone).
- **Decision made during planning, not fully specified in the spec** (flagged for the user, not hidden): the exact quality-rating field UI (a `<select>` per field with a "No opinion" blank option, rather than e.g. a star rating or button group) and the exact event-subtype/rating enum option labels were decided here to match `models.py`'s actual enum values — reasonable implementation detail, not a design-level decision requiring separate sign-off.
