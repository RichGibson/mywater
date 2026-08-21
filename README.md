# mywater precompute pipeline

Precompute pipeline for the mywater community water-quality reporting site.
It fetches Lake County CA parcel and roadway data, clusters parcels into
~8-parcel anonymization groups along street frontage, and loads the result
into a SpatiaLite database so residents can report issues either at their
exact parcel or "obscured" to a cluster of neighboring parcels for privacy.

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

The Python interpreter used to run this pipeline (or its tests) **must**
support `sqlite3.Connection.enable_load_extension`, because `precompute/load.py`
loads the SpatiaLite extension into the sqlite3 connection. macOS
system/Xcode-bundled Python typically does **not** support this — confirmed
on this development machine that a `python3 -m venv .venv` built from the
macOS system/Xcode Python 3.9 lacks `enable_load_extension` entirely.

The known-working path on this development machine is a conda environment
with `libspatialite` installed via conda-forge:

```bash
conda create -n mywater python=3.12
conda activate mywater
conda install -c conda-forge libspatialite
pip install -r requirements.txt
```

## Running tests

From the `projects/mywater` directory, with the `mywater` conda environment active:

```bash
pytest tests/ -v
```

## Running the pipeline

From the `projects/mywater` directory, with the `mywater` conda environment active:

```bash
python -m precompute.run
```

This deletes and rebuilds `mywater.db` from scratch on every run.

## Tables

- `parcels` — one row per Lake County parcel (APN, situs address, geometry,
  centroid, and the `parcel_clusters` row it belongs to).
- `parcel_clusters` — one row per anonymization cluster of ~8 neighboring
  parcels along a street. Includes an `anonymization_safe` flag: `1` if the
  cluster has at least `MIN_CLUSTER_SIZE` (6) parcels and is safe to offer as
  an obscured-location target, `0` if the cluster is smaller than that (an
  unavoidable outcome for streets with very few parcels total) and should
  **not** be offered for obscured reporting, since it would not actually
  anonymize the reporter's location.

## Important: cluster/parcel IDs are not stable across re-runs

`parcel_clusters.id` and `parcels.id` are auto-incrementing and assigned in
whatever order the Lake County ArcGIS service returns records — this order
is NOT guaranteed stable between runs. Re-running this pipeline (e.g. to
pick up updated county parcel data) will assign different IDs to the same
physical parcels/clusters.

This matters once a `reports` table exists (see the design spec) referencing
`parcel_id`/`cluster_id` as foreign keys: re-running this pipeline after
go-live would silently orphan or misattribute existing user reports to the
wrong location. Do not re-run this pipeline against a live database with
existing reports without first designing a stable identifier (e.g. a natural
key derived from APN or street_name + ordinal position) for anything that
needs to survive a re-run. This is a known limitation, not yet fixed — flag
it when designing the backend plan.
