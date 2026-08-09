# mywater — Design Spec

**Date**: 2026-08-08
**Status**: Approved, pending implementation planning

## Overview & Scope

A public, map-based site for the Clearlake Oaks County Water District (CLOCWD) service area where residents report water quality events and ongoing issues, with optional photos. It replaces scattered Facebook complaints with a structured, persistent, publicly visible record.

**Motivation**: Two water main breaks in the last two months affecting some of the ~800 houses in the Keys neighborhood, plus recurring reports of bad smell, bad taste, and bad-looking water. Nearby houses appear to have dramatically different water quality at different times, which a shared map/timeline can help surface.

**Core capabilities**:
- Click anywhere in the CLOCWD service area to file a report, either with your exact parcel or an obscured (anonymized) location.
- Two report types: **Event** (one-off: main break, outage, boil-water notice) and **Quality report** (ongoing: taste/smell/color/pressure ratings).
- Optional photo per report.
- Public map + synced timeline view. No login required.
- Immediate publish. Lightweight abuse mitigation (no moderation queue, no accounts).

**Anonymization guarantee**: for obscured reports, the exact address is never captured client-side at all — not stored, not transiently held, not even sent to the server. The map shows precomputed clusters of ~8 neighboring parcels directly; the user picks their cluster, not a point. This makes deanonymization impossible even via a DB leak or admin access, because the precise location was never captured in the first place.

**Deferred to future** (explicitly out of scope for v1): address lookup/geocoding for non-obscured reports, admin moderation UI, accounts/auth, CAPTCHA.

## Architecture & Stack

Per the existing site-building playbook (`projects/websites-readme.md`, `projects/template-site/PLAYBOOK.md`), this is a **dynamic site** (needs a running server for reports/photos/timeline), following the same pattern as `megazoomquilt.com`.

- **Backend**: FastAPI + Jinja2 + HTMX, following `projects/template-code` conventions.
- **Database**: SQLite + SpatiaLite extension, single file on the Hetzner box. Chosen over PostGIS to avoid running a separate DB service; chosen over plain SQLite (no spatial extension) so spatial queries can be expressed directly in SQL if needed later, rather than only via an in-app index.
- **Frontend map**: Leaflet.js + OSM tiles for the base map (streets, orientation); parcels, clusters, and report markers rendered as GeoJSON overlays on top.
- **Parcel data source** (verified live 2026-08-08): Lake County CA's official ArcGIS service, `https://gis.lakecountyca.gov/server/rest/services/Parcels/MapServer`. Layer 0 (`Parcels`, polygons) has `APN` (unique ID), `SITUSSTR`/`SITUSNUM`/`SITUSFULL` (situs street name/number/city), `X`/`Y` (centroid, WGS84), and geometry (requestable reprojected to WGS84 via `outSR=4326`). Layer 1 (`Roadways`, polylines) has `ROADNAME` in the same coordinate system — used for street-frontage ordering instead of a separate OSM street layer, since names are guaranteed to match `SITUSSTR`. OSM tiles are still used for the visual base map.
- **Service-area scoping** (revised from original plan): CLOCWD publishes its service-area boundary only as static PNG/JPEG images on clocwd.org, not as a downloadable vector file (confirmed 2026-08-08, no GeoJSON/KML/shapefile available anywhere). For v1, in-scope parcels are determined by filtering `SITUSFULL` for the Clearlake Oaks community name rather than clipping to an exact district polygon. This is an approximation — it may include a small number of parcels the water district doesn't technically serve, or miss edge parcels — acceptable for v1 given the alternative is manually digitizing the boundary from a raster image.
- **Photos**: uploaded to Cloudflare R2; the database stores only the resulting object URL, not the file itself.
- **Hosting**: Hetzner VM (app + SQLite file, systemd service), Cloudflare in front as CDN/SSL terminator. Domain registration (Porkbun) and DNS/Cloudflare setup are deferred until ready to go live — not required to build or test locally.
- **Precompute step**: a one-time (re-runnable) offline Python script using `requests` + `shapely` (no GeoPandas — the ArcGIS REST source reprojects to WGS84 server-side via `outSR=4326`, and the clustering logic is pure geometry ops, not spatial joins, so the heavier GeoPandas/GDAL/PROJ stack isn't needed) that builds the `parcels` and `parcel_clusters` tables before first deploy. The running app never performs live geometric clustering — it only reads precomputed tables.

## Data Model

```
parcels
  id, geometry, cluster_id (FK -> parcel_clusters), centroid_lat, centroid_lng

parcel_clusters
  id, geometry, centroid_lat, centroid_lng, parcel_count

reports
  id, report_type            -- 'event' | 'quality'
  obscured                   -- bool
  parcel_id                  -- FK -> parcels; set if NOT obscured (exact parcel picked)
  cluster_id                 -- FK -> parcel_clusters; set if obscured
  created_at
  free_text                  -- capped length (e.g. 500 chars)
  photo_url                  -- nullable, R2 object URL

  -- quality-report fields, nullable for event reports
  taste, smell, color, pressure   -- each a 3-point enum: good | off | bad

  -- event fields, nullable for quality reports
  event_subtype               -- 'main_break' | 'outage' | 'boil_notice' | 'other'
  ongoing                      -- bool

submission_log
  ip_hash, cookie_id, created_at   -- rate-limiting only; never displayed publicly
```

No raw lat/lng is ever stored in `reports` — every report resolves to either a specific `parcel_id` or a `cluster_id`, both drawn from the precomputed spatial layers. Marker display position for non-obscured reports is the parcel centroid, not the literal click point, so no raw coordinate is persisted even for identified reports.

`submission_log` is kept separate from `reports` so rate-limit bookkeeping never mixes with public report data.

## Anonymization Pipeline (Precompute)

Run once before first deploy, and again only if underlying parcel data changes:

1. **Fetch** parcels from Lake County's `Parcels/MapServer` layer 0 where `SITUSFULL` matches the Clearlake Oaks community name, and roadway centerlines from layer 1, both reprojected to WGS84.
2. **Cluster** parcels into contiguous groups of roughly 8 along street frontage (group by `SITUSSTR`, order by position along the matching `ROADNAME` centerline, bucket consecutive parcels), producing each cluster's boundary geometry (union of member parcels) and a centroid snapped to the street midpoint of that group.
3. **Load** results into SQLite/SpatiaLite: `parcels` (each tagged with its `cluster_id`) and `parcel_clusters`.
4. **Sanity check**: every parcel belongs to exactly one cluster; every cluster has roughly 6-10 members. Flag outliers (cul-de-sacs, sparse rural stretches) for manual review rather than forcing them into an unnatural grouping. If a parcel can't be matched at all (e.g. a gap in county data), log and exclude it rather than crashing the pipeline or silently dropping it unflagged.

## Report Submission Flow & Abuse Mitigation

**Flow**:
1. User picks "show my location" or "obscure location" before interacting with the map.
2. Map switches mode accordingly: *show-my-location* highlights the parcel under the cursor and confirms on click; *obscure* shows cluster boundaries and confirms the clicked cluster.
3. An HTMX partial form appears: report type (Event / Quality), type-specific fields, capped free-text, optional photo.
4. On submit: server validates fields, checks rate limit, uploads photo to R2 if present, inserts the `reports` row, and returns the updated marker/timeline partial.

**Abuse mitigation** (deliberately lightweight, per project preference — no accounts, no CAPTCHA for v1):
- **Rate limit**: cap submissions per IP and per cookie, whichever is stricter — starting guess of 5 reports/day per identity, easily tunable later since it's just a threshold query against `submission_log`. IP read from Cloudflare's `CF-Connecting-IP` header once deployed behind Cloudflare. Cookie is a random ID set on first visit, carries no PII.
- **Photo constraints**: max size (~5MB), type allowlist (jpg/png/heic), validated both client- and server-side.
- **Free-text cap**: length limit only; no content filtering in v1.
- **No moderation queue**: reports publish immediately; abusive ones are removed after the fact via direct DB/admin access.

## Map & Timeline UI

- **Map** (Leaflet + OSM tiles): base layer for streets/orientation. Toggleable overlays: parcels (shown when placing an exact report), clusters (shown when obscuring), report markers (always visible, styled by type and recency).
- **Timeline**: a date-range scrubber below the map drives which report markers are shown, via an HTMX request that returns a fresh GeoJSON partial; a small JS layer swaps the Leaflet markers on each update. The scrubber is the map/timeline sync mechanism — no separate timeline-only feed in v1.
- **Report detail**: clicking a marker opens a panel with type, ratings (if quality), free text, photo (if present), and timestamp. Obscured reports show only the cluster label (e.g. "area near X St"), never a parcel-level address.
- **Legend**: key for marker styling (event vs quality, recency shading).

## Error Handling

- Click outside the CLOCWD service area boundary → rejected with "please select a point within the service district," checked client-side against the boundary GeoJSON and re-checked server-side.
- Rate limit exceeded → friendly, non-punitive message ("you've reached today's report limit — try again tomorrow").
- Photo upload failure (size/type/R2 error) → inline form error; submission blocked until fixed or photo removed, but text-only submission still allowed.
- Malformed/missing required fields → standard inline validation via HTMX partial re-render.
- Precompute pipeline failures (unmatched parcels) → logged and excluded, never silently dropped without a trace.

## Testing / Verification

Split by stakes: automated tests where correctness is load-bearing (privacy guarantee, abuse mitigation), manual checks where it's visual/low-stakes.

- **Automated tests**: precompute clustering (cluster sizes land in 6-10, every parcel assigned to exactly one cluster, unmatched parcels are logged not dropped), the `parcel_id`/`cluster_id` mutual-exclusivity invariant on `reports`, and rate-limit threshold logic in `submission_log` queries.
- **Manual verification**: map/timeline UI, HTMX partial swaps, end-to-end pass before launch — submit both report types, obscured and non-obscured, with and without photos; confirm rate limiting triggers past the threshold in the running app; confirm the timeline scrubber filters markers correctly.

## Deployment

Per the existing playbook's dynamic-site pattern:
- App + SQLite file run on the Hetzner instance as a systemd service.
- Cloudflare in front as CDN/SSL terminator.
- Photos in Cloudflare R2, separate from the Hetzner disk.
- Domain: deferred. Register at Porkbun and point nameservers to Cloudflare when ready to go live; not required for local build/test.
- Once live: add to the site network (nav/footer update across `projects/template-site` and other sites, per playbook step 8).
