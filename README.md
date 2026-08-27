# mywater

A public map-based site for Clearlake Oaks (Lake County, CA) residents to
report water quality events (main breaks, outages, boil-water notices) and
ongoing issues (taste, smell, color, pressure), either at their exact
parcel or "obscured" to an anonymized cluster of neighboring parcels.

The project has three parts, in the order you'd normally run them:

1. **`precompute/`** — an offline pipeline that fetches Lake County parcel
   and roadway data, clusters parcels into ~8-parcel anonymization groups,
   and builds `mywater.db` (read-only from the web app).
2. **Backend API** (`main.py`, `routers/`, `models.py`, `rate_limit.py`,
   `photos.py`) — FastAPI JSON/GeoJSON endpoints for submitting and reading
   reports, backed by its own `mywater_app.db`.
3. **Frontend** (`templates/`, `static/`) — the map, report-submission
   panel, timeline, and About/FAQ pages, served by the same FastAPI app.

## DEPLOYMENT: Cloudflare firewall is REQUIRED before going live

**The backend API trusts the `CF-Connecting-IP` header unconditionally** to
identify clients for rate limiting (`routers/reports.py`'s `_client_ip`).
This is safe ONLY when the Hetzner origin server is reachable exclusively
through Cloudflare's proxy, because Cloudflare overwrites this header and a
client cannot forge it through Cloudflare.

If the origin is EVER directly reachable — a firewall misconfiguration, or
someone simply discovers the origin IP — a client can send an arbitrary
`CF-Connecting-IP: <anything>` on each request and trivially bypass the
IP-based half of rate limiting (the cookie-based half is already
voluntary/discardable, so IP-based limiting is the load-bearing protection
against abuse).

**Before this app goes live, the Hetzner origin MUST be firewalled to
accept connections only from Cloudflare's published IP ranges:**
https://www.cloudflare.com/ips/

This is a deployment/infrastructure requirement, not something the
application code can enforce on its own — there is no code-level mitigation
for a misconfigured firewall.

## Setup

The Python interpreter **must** support
`sqlite3.Connection.enable_load_extension`, because `precompute/load.py`
(reused by the backend's `db.py`) loads the SpatiaLite extension into the
sqlite3 connection. macOS system/Xcode-bundled Python typically does **not**
support this — confirmed on this development machine that a
`python3 -m venv .venv` built from the macOS system/Xcode Python 3.9 lacks
`enable_load_extension` entirely.

The known-working path on this development machine is a conda environment
with `libspatialite` installed via conda-forge:

```bash
conda create -n mywater python=3.12
conda activate mywater
conda install -c conda-forge libspatialite
pip install -r requirements.txt
```

### Environment variables

```bash
cp .env.example .env
```

Then edit `.env`:

- **`RATE_LIMIT_PEPPER`** — required. The app fails loudly (raises at the
  first rate-limit check, not at startup) if this is left unset or empty —
  an unset pepper would make stored IP hashes trivially reversible. Set it
  to any random string, e.g. `python3 -c "import secrets; print(secrets.token_hex(32))"`.
- `RATE_LIMIT_PER_DAY` — optional, defaults to `5` if unset.
- `R2_*` — optional for local development. Only needed to actually upload
  photos to Cloudflare R2; without them, a photo-attached submission fails
  with a handled 400 error (not a crash), and text-only submissions work
  fine.

## Running the precompute pipeline

From the `projects/mywater` directory, with the `mywater` conda environment
active:

```bash
python -m precompute.run
```

This deletes and rebuilds `mywater.db` from scratch on every run. Run it
once before first use, and again only if you want to pick up updated county
parcel data (see the ID-stability note below before doing this on a
database with real reports in it).

## Running the web app

From the `projects/mywater` directory, with the `mywater` conda environment
active and `mywater.db` already built (see above):

```bash
uvicorn main:app --reload --port 8765
```

Then open:

- `http://localhost:8765/` — the map
- `http://localhost:8765/about` — the About/FAQ page
- `http://localhost:8765/healthz` — health check, returns `{"status": "ok"}`

`mywater_app.db` (the `reports`/`submission_log` tables) is created
automatically on first startup if it doesn't already exist — no separate
setup step needed.

## Running tests

From the `projects/mywater` directory, with the `mywater` conda environment
active:

```bash
pytest tests/ -v
```

Automated tests cover the precompute pipeline, the backend API (via
`TestClient` against temporary isolated databases), and page-rendering
smoke tests for the frontend routes. There is no browser-based test runner
in this project — map/panel/timeline interactivity and mobile layout are
verified manually.

## Tables

`mywater.db` (precompute-owned, read-only from the backend):

- `parcels` — one row per Lake County parcel (APN, situs address, geometry,
  centroid, and the `parcel_clusters` row it belongs to).
- `parcel_clusters` — one row per anonymization cluster of ~8 neighboring
  parcels along a street. Includes an `anonymization_safe` flag: `1` if the
  cluster has at least `MIN_CLUSTER_SIZE` (6) parcels and is safe to offer as
  an obscured-location target, `0` if the cluster is smaller than that (an
  unavoidable outcome for streets with very few parcels total) and should
  **not** be offered for obscured reporting, since it would not actually
  anonymize the reporter's location.

`mywater_app.db` (backend-owned; precompute never touches this file):

- `reports` — one row per submitted report. Non-obscured reports store both
  `parcel_id` and `parcel_apn`; reads resolve by `parcel_apn` (see below),
  not `parcel_id`. Obscured reports store only `cluster_id`.
- `submission_log` — IP-hash/cookie-hash + timestamp, used only for rate
  limiting; never displayed publicly.

## Important: cluster IDs are not stable across precompute re-runs

`parcel_clusters.id` is auto-incrementing and assigned in whatever order
the Lake County ArcGIS service returns records — this order is NOT
guaranteed stable between `precompute/run.py` re-runs. A stored
`reports.cluster_id` could silently resolve to a *different* cluster after
a re-run.

The backend already fails closed for this case: the read path re-checks
`anonymization_safe = 1` on the joined cluster at query time, so a report
whose cluster becomes unsafe (or no longer exists) after a re-run shows no
location rather than leaking one. But a report could still land on a
*different, still-safe* cluster and display the wrong street label — not a
deanonymization, but a data-accuracy issue.

(Note: the equivalent problem for `parcels.id`/`parcel_id` is already
fixed — reports store and resolve by the parcel's permanent APN, not the
unstable `parcel_id`, so a precompute re-run cannot misattribute a
non-obscured report to the wrong physical parcel. See `parcel_apn` in
`db_app_schema.sql` and `routers/reports.py`.)

**Do not re-run `precompute/run.py` against a database with real reports in
it** without accepting the cluster-drift risk above, or without first
designing a stable cluster key (e.g. derived from `street_name` + ordinal
position) — this is a known, documented limitation, not yet fixed.
