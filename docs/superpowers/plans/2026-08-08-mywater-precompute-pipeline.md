# mywater Precompute Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, re-runnable Python pipeline that fetches Lake County parcel and roadway data, clusters parcels into ~8-parcel anonymization groups along street frontage, and loads the results into a SpatiaLite-backed SQLite database — the foundation the mywater backend (a later plan) will read from.

**Architecture:** Three pure/testable modules (`fetch.py`, `cluster.py`, `load.py`) wired together by a CLI entrypoint (`run.py`). `fetch.py` talks to Lake County's live ArcGIS REST service; `cluster.py` is pure Shapely geometry logic with no I/O; `load.py` writes to SQLite/SpatiaLite. This is the first of three plans for the mywater project — the backend API and frontend UI are separate plans that consume the database this one produces.

**Tech Stack:** Python 3, `requests`, `shapely`, `pytest`, SQLite + SpatiaLite extension.

## Global Constraints

- Parcel/roadway data source: `https://gis.lakecountyca.gov/server/rest/services/Parcels/MapServer` — layer 0 (`Parcels`, fields `APN`, `SITUSSTR`, `SITUSNUM`, `SITUSFULL`), layer 1 (`Roadways`, field `ROADNAME`). Query with `outSR=4326` to get WGS84 directly.
- In-scope parcels: `SITUSFULL LIKE '%CLEARLAKE OAKS%'` (community-name filter; no vector CLOCWD boundary exists).
- Cluster sizing: target 8 parcels per cluster, acceptable range 6-10; outside that range gets flagged, not silently forced.
- No GeoPandas — `requests` + `shapely` only. No live geometric clustering at request time; this pipeline runs offline and the running app only reads its output tables.
- Unmatched/unmatchable parcels (no geometry, no street name) are logged and excluded, never silently dropped without a trace.
- The pipeline is the only place `parcels` and `parcel_clusters` get written; nothing else in the mywater project writes to them.

---

## File Structure

```
projects/mywater/
  requirements.txt
  precompute/
    __init__.py
    fetch.py       -- ArcGIS REST client (parcels, roadways)
    cluster.py      -- pure clustering logic, no I/O
    load.py         -- SQLite/SpatiaLite connection, schema init, writes
    schema.sql       -- DDL for parcels + parcel_clusters
    run.py          -- CLI: fetch -> cluster -> load -> report
  tests/
    __init__.py
    test_fetch.py
    test_cluster.py
    test_load.py
  .gitignore        -- excludes mywater.db, __pycache__
```

---

### Task 1: Project scaffolding + SpatiaLite schema and connection

**Files:**
- Create: `projects/mywater/requirements.txt`
- Create: `projects/mywater/.gitignore`
- Create: `projects/mywater/precompute/__init__.py`
- Create: `projects/mywater/precompute/schema.sql`
- Create: `projects/mywater/precompute/load.py`
- Create: `projects/mywater/tests/__init__.py`
- Test: `projects/mywater/tests/test_load.py`

**Interfaces:**
- Produces: `precompute.load.connect(db_path: str) -> sqlite3.Connection` (SpatiaLite extension loaded, foreign keys on). `precompute.load.init_schema(conn: sqlite3.Connection, schema_path: str | Path) -> None`.

- [ ] **Step 1: Install SpatiaLite locally (not code — required before tests can run)**

macOS: `brew install libspatialite`
Debian/Ubuntu (for later Hetzner deploy reference): `apt install libsqlite3-mod-spatialite`

- [ ] **Step 2: Create the project scaffolding**

`projects/mywater/requirements.txt`:
```
requests
shapely
pytest
```

`projects/mywater/.gitignore`:
```
__pycache__/
*.pyc
mywater.db
.venv/
```

`projects/mywater/precompute/__init__.py`: (empty file)

`projects/mywater/tests/__init__.py`: (empty file)

Then set up the environment:
```bash
cd projects/mywater
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 3: Write the schema**

`projects/mywater/precompute/schema.sql`:
```sql
SELECT InitSpatialMetaData(1);

CREATE TABLE parcel_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    street_name TEXT NOT NULL,
    centroid_lat REAL NOT NULL,
    centroid_lng REAL NOT NULL,
    parcel_count INTEGER NOT NULL
);
SELECT AddGeometryColumn('parcel_clusters', 'geometry', 4326, 'MULTIPOLYGON', 'XY');
SELECT CreateSpatialIndex('parcel_clusters', 'geometry');

CREATE TABLE parcels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apn TEXT NOT NULL UNIQUE,
    situsstr TEXT,
    situsnum TEXT,
    cluster_id INTEGER NOT NULL REFERENCES parcel_clusters(id),
    centroid_lat REAL NOT NULL,
    centroid_lng REAL NOT NULL
);
SELECT AddGeometryColumn('parcels', 'geometry', 4326, 'MULTIPOLYGON', 'XY');
SELECT CreateSpatialIndex('parcels', 'geometry');
```

- [ ] **Step 4: Write the failing tests for connect() and init_schema()**

`projects/mywater/tests/test_load.py`:
```python
from pathlib import Path

import pytest

from precompute.load import connect, init_schema

SCHEMA_PATH = Path(__file__).parent.parent / "precompute" / "schema.sql"


@pytest.fixture
def conn():
    connection = connect(":memory:")
    init_schema(connection, SCHEMA_PATH)
    yield connection
    connection.close()


def test_connect_loads_spatialite_extension(conn):
    version = conn.execute("SELECT spatialite_version()").fetchone()[0]
    assert version


def test_init_schema_creates_expected_tables(conn):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"parcels", "parcel_clusters"} <= tables
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `cd projects/mywater && python -m pytest tests/test_load.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'precompute.load'` (or similar — the module doesn't exist yet)

- [ ] **Step 6: Implement connect() and init_schema()**

`projects/mywater/precompute/load.py`:
```python
import sqlite3

_EXTENSION_CANDIDATES = [
    "mod_spatialite",
    "mod_spatialite.dylib",
    "mod_spatialite.so",
    "/opt/homebrew/lib/mod_spatialite.dylib",
    "/usr/local/lib/mod_spatialite.dylib",
    "/usr/lib/x86_64-linux-gnu/mod_spatialite.so",
]


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.enable_load_extension(True)
    last_error = None
    loaded = False
    for candidate in _EXTENSION_CANDIDATES:
        try:
            conn.load_extension(candidate)
            loaded = True
            break
        except sqlite3.OperationalError as exc:
            last_error = exc
    conn.enable_load_extension(False)
    if not loaded:
        raise RuntimeError(
            "Could not load the SpatiaLite extension from any known location. "
            "Install it first: `brew install libspatialite` on macOS, "
            "`apt install libsqlite3-mod-spatialite` on Debian/Ubuntu."
        ) from last_error
    return conn


def init_schema(conn, schema_path):
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.commit()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd projects/mywater && python -m pytest tests/test_load.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add projects/mywater/requirements.txt projects/mywater/.gitignore \
  projects/mywater/precompute/__init__.py projects/mywater/precompute/schema.sql \
  projects/mywater/precompute/load.py projects/mywater/tests/__init__.py \
  projects/mywater/tests/test_load.py
git commit -m "mywater: SpatiaLite schema and connection setup"
```

---

### Task 2: Clustering algorithm

**Files:**
- Create: `projects/mywater/precompute/cluster.py`
- Test: `projects/mywater/tests/test_cluster.py`

**Interfaces:**
- Consumes: nothing from other modules (pure logic, no I/O).
- Produces:
  - `TARGET_CLUSTER_SIZE = 8`, `MIN_CLUSTER_SIZE = 6`, `MAX_CLUSTER_SIZE = 10`
  - `match_roadway(street_name: str, roadways: list[dict]) -> shapely.geometry.LineString | None` — `roadways` items have keys `roadname: str`, `geometry: shapely geometry`.
  - `order_parcels_along_street(parcels: list[dict], roadway_line: LineString | None) -> list[dict]` — `parcels` items have keys `apn`, `situsnum`, `geometry` (Polygon/MultiPolygon).
  - `bucket_parcels(ordered_parcels: list[dict], target: int = TARGET_CLUSTER_SIZE, max_size: int = MAX_CLUSTER_SIZE) -> list[list[dict]]`
  - `build_cluster_record(cluster_parcels: list[dict], roadway_line: LineString | None) -> dict` with keys `geometry`, `centroid_lat`, `centroid_lng`, `parcel_count`, `members` (= `cluster_parcels`).
  - `cluster_parcels_by_street(parcels: list[dict], roadways: list[dict]) -> tuple[list[dict], list[str], list[int]]` returns `(clusters, excluded_apns, outlier_cluster_indices)`. Each cluster dict additionally has `street_name`. `parcels` items need keys `apn`, `situsstr`, `situsnum`, `geometry`.
  - Later tasks (load, run) consume `cluster_parcels_by_street`'s return value directly.

- [ ] **Step 1: Write failing tests for bucket_parcels**

`projects/mywater/tests/test_cluster.py`:
```python
from shapely.geometry import LineString, Polygon

from precompute.cluster import (
    bucket_parcels,
    build_cluster_record,
    cluster_parcels_by_street,
    match_roadway,
    order_parcels_along_street,
)


def _square(cx, cy, size=0.2):
    return Polygon(
        [
            (cx - size / 2, cy - size / 2),
            (cx + size / 2, cy - size / 2),
            (cx + size / 2, cy + size / 2),
            (cx - size / 2, cy + size / 2),
        ]
    )


def test_bucket_parcels_splits_evenly_sized_street_into_target_groups():
    parcels = [{"apn": str(i)} for i in range(16)]
    buckets = bucket_parcels(parcels, target=8, max_size=10)
    assert [len(b) for b in buckets] == [8, 8]


def test_bucket_parcels_folds_small_remainder_into_last_bucket():
    parcels = [{"apn": str(i)} for i in range(20)]
    buckets = bucket_parcels(parcels, target=8, max_size=10)
    assert [len(b) for b in buckets] == [8, 8, 4]


def test_bucket_parcels_keeps_single_bucket_when_under_max():
    parcels = [{"apn": str(i)} for i in range(9)]
    buckets = bucket_parcels(parcels, target=8, max_size=10)
    assert [len(b) for b in buckets] == [9]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd projects/mywater && python -m pytest tests/test_cluster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'precompute.cluster'`

- [ ] **Step 3: Implement bucket_parcels**

`projects/mywater/precompute/cluster.py`:
```python
from shapely.ops import linemerge, unary_union

TARGET_CLUSTER_SIZE = 8
MIN_CLUSTER_SIZE = 6
MAX_CLUSTER_SIZE = 10


def bucket_parcels(ordered_parcels, target=TARGET_CLUSTER_SIZE, max_size=MAX_CLUSTER_SIZE):
    clusters = []
    n = len(ordered_parcels)
    i = 0
    while i < n:
        remaining = n - i
        if remaining <= max_size:
            clusters.append(ordered_parcels[i:])
            i = n
        else:
            clusters.append(ordered_parcels[i : i + target])
            i += target
    return clusters
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd projects/mywater && python -m pytest tests/test_cluster.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write failing tests for match_roadway and order_parcels_along_street**

Append to `projects/mywater/tests/test_cluster.py`:
```python
def test_match_roadway_finds_case_insensitive_match():
    line = LineString([(0, 0), (10, 0)])
    roadways = [{"roadname": "Main St", "geometry": line}]
    result = match_roadway("MAIN ST", roadways)
    assert result is not None
    assert result.equals(line)


def test_match_roadway_returns_none_when_no_match():
    roadways = [{"roadname": "Elm St", "geometry": LineString([(0, 0), (10, 0)])}]
    assert match_roadway("MAIN ST", roadways) is None


def test_order_parcels_along_street_orders_by_projected_distance():
    line = LineString([(0, 0), (10, 0)])
    parcels = [
        {"apn": "C", "geometry": _square(7, 0.1), "situsnum": "300"},
        {"apn": "A", "geometry": _square(1, 0.1), "situsnum": "100"},
        {"apn": "B", "geometry": _square(4, 0.1), "situsnum": "200"},
    ]
    ordered = order_parcels_along_street(parcels, line)
    assert [p["apn"] for p in ordered] == ["A", "B", "C"]


def test_order_parcels_along_street_falls_back_to_situsnum_without_roadway():
    parcels = [
        {"apn": "C", "situsnum": "300", "geometry": _square(7, 0.1)},
        {"apn": "A", "situsnum": "100", "geometry": _square(1, 0.1)},
        {"apn": "B", "situsnum": "200", "geometry": _square(4, 0.1)},
    ]
    ordered = order_parcels_along_street(parcels, None)
    assert [p["apn"] for p in ordered] == ["A", "B", "C"]
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd projects/mywater && python -m pytest tests/test_cluster.py -v`
Expected: FAIL — `match_roadway` and `order_parcels_along_street` not defined

- [ ] **Step 7: Implement match_roadway and order_parcels_along_street**

Append to `projects/mywater/precompute/cluster.py`:
```python
def match_roadway(street_name, roadways):
    matches = [
        r["geometry"]
        for r in roadways
        if r["roadname"].strip().upper() == street_name.strip().upper()
    ]
    if not matches:
        return None
    return linemerge(unary_union(matches))


def order_parcels_along_street(parcels, roadway_line):
    if roadway_line is not None:
        return sorted(parcels, key=lambda p: roadway_line.project(p["geometry"].centroid))

    def numeric_key(p):
        try:
            return int(p["situsnum"])
        except (TypeError, ValueError):
            return 0

    return sorted(parcels, key=numeric_key)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd projects/mywater && python -m pytest tests/test_cluster.py -v`
Expected: PASS (7 tests)

- [ ] **Step 9: Write failing tests for build_cluster_record**

Append to `projects/mywater/tests/test_cluster.py`:
```python
import pytest


def test_build_cluster_record_centroid_is_street_midpoint_of_members():
    line = LineString([(0, 0), (10, 0)])
    parcels = [
        {"apn": "A", "geometry": _square(2, 0.1)},
        {"apn": "B", "geometry": _square(4, 0.1)},
    ]
    record = build_cluster_record(parcels, line)
    assert record["parcel_count"] == 2
    assert record["centroid_lng"] == pytest.approx(3.0, abs=0.01)
    assert record["centroid_lat"] == pytest.approx(0.0, abs=0.01)
    assert record["members"] == parcels


def test_build_cluster_record_falls_back_to_union_centroid_without_roadway():
    parcels = [
        {"apn": "A", "geometry": _square(0, 0)},
        {"apn": "B", "geometry": _square(2, 0)},
    ]
    record = build_cluster_record(parcels, None)
    assert record["centroid_lng"] == pytest.approx(1.0, abs=0.01)
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `cd projects/mywater && python -m pytest tests/test_cluster.py -v`
Expected: FAIL — `build_cluster_record` not defined

- [ ] **Step 11: Implement build_cluster_record**

Append to `projects/mywater/precompute/cluster.py`:
```python
def build_cluster_record(cluster_parcels, roadway_line):
    geoms = [p["geometry"] for p in cluster_parcels]
    union_geom = unary_union(geoms)
    if roadway_line is not None:
        distances = [roadway_line.project(p["geometry"].centroid) for p in cluster_parcels]
        mid_distance = (min(distances) + max(distances)) / 2
        centroid_point = roadway_line.interpolate(mid_distance)
    else:
        centroid_point = union_geom.centroid
    return {
        "geometry": union_geom,
        "centroid_lat": centroid_point.y,
        "centroid_lng": centroid_point.x,
        "parcel_count": len(cluster_parcels),
        "members": cluster_parcels,
    }
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `cd projects/mywater && python -m pytest tests/test_cluster.py -v`
Expected: PASS (9 tests)

- [ ] **Step 13: Write failing tests for cluster_parcels_by_street (the full pipeline function)**

Append to `projects/mywater/tests/test_cluster.py`:
```python
def test_cluster_parcels_by_street_excludes_parcels_missing_geometry_or_street():
    line = LineString([(0, 0), (10, 0)])
    roadways = [{"roadname": "MAIN ST", "geometry": line}]
    parcels = [
        {"apn": "A", "situsstr": "MAIN ST", "situsnum": "100", "geometry": _square(1, 0.1)},
        {"apn": "B", "situsstr": "MAIN ST", "situsnum": "200", "geometry": _square(2, 0.1)},
        {"apn": "MISSING_GEOM", "situsstr": "MAIN ST", "situsnum": "300", "geometry": None},
        {"apn": "MISSING_STREET", "situsstr": "", "situsnum": "400", "geometry": _square(4, 0.1)},
    ]
    clusters, excluded, outliers = cluster_parcels_by_street(parcels, roadways)
    assert set(excluded) == {"MISSING_GEOM", "MISSING_STREET"}
    assert sum(c["parcel_count"] for c in clusters) == 2


def test_cluster_parcels_by_street_flags_small_street_as_outlier():
    line = LineString([(0, 0), (10, 0)])
    roadways = [{"roadname": "SHORT LN", "geometry": line}]
    parcels = [
        {
            "apn": f"P{i}",
            "situsstr": "SHORT LN",
            "situsnum": str(100 + i),
            "geometry": _square(i, 0.1),
        }
        for i in range(3)
    ]
    clusters, excluded, outlier_indices = cluster_parcels_by_street(parcels, roadways)
    assert len(clusters) == 1
    assert clusters[0]["parcel_count"] == 3
    assert outlier_indices == [0]


def test_cluster_parcels_by_street_does_not_flag_target_sized_cluster():
    line = LineString([(0, 0), (10, 0)])
    roadways = [{"roadname": "LONG LN", "geometry": line}]
    parcels = [
        {
            "apn": f"P{i}",
            "situsstr": "LONG LN",
            "situsnum": str(100 + i),
            "geometry": _square(i, 0.1),
        }
        for i in range(8)
    ]
    clusters, excluded, outlier_indices = cluster_parcels_by_street(parcels, roadways)
    assert len(clusters) == 1
    assert outlier_indices == []
```

- [ ] **Step 14: Run tests to verify they fail**

Run: `cd projects/mywater && python -m pytest tests/test_cluster.py -v`
Expected: FAIL — `cluster_parcels_by_street` not defined

- [ ] **Step 15: Implement cluster_parcels_by_street**

Append to `projects/mywater/precompute/cluster.py`:
```python
def cluster_parcels_by_street(parcels, roadways):
    valid, excluded = [], []
    for p in parcels:
        if p.get("geometry") is None or not p.get("situsstr"):
            excluded.append(p.get("apn"))
        else:
            valid.append(p)

    by_street = {}
    for p in valid:
        by_street.setdefault(p["situsstr"], []).append(p)

    clusters = []
    for street_name, street_parcels in by_street.items():
        roadway_line = match_roadway(street_name, roadways)
        ordered = order_parcels_along_street(street_parcels, roadway_line)
        for bucket in bucket_parcels(ordered):
            record = build_cluster_record(bucket, roadway_line)
            record["street_name"] = street_name
            clusters.append(record)

    outlier_indices = [
        i
        for i, c in enumerate(clusters)
        if not (MIN_CLUSTER_SIZE <= c["parcel_count"] <= MAX_CLUSTER_SIZE)
    ]
    return clusters, excluded, outlier_indices
```

- [ ] **Step 16: Run all cluster tests to verify they pass**

Run: `cd projects/mywater && python -m pytest tests/test_cluster.py -v`
Expected: PASS (12 tests)

- [ ] **Step 17: Commit**

```bash
git add projects/mywater/precompute/cluster.py projects/mywater/tests/test_cluster.py
git commit -m "mywater: parcel clustering algorithm"
```

---

### Task 3: ArcGIS REST fetch client

**Files:**
- Create: `projects/mywater/precompute/fetch.py`
- Test: `projects/mywater/tests/test_fetch.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `PARCELS_MAPSERVER_URL: str` constant, `"https://gis.lakecountyca.gov/server/rest/services/Parcels/MapServer"`.
  - `fetch_parcels(community_name: str, base_url: str = PARCELS_MAPSERVER_URL) -> list[dict]` — each item has keys `apn`, `situsstr`, `situsnum`, `situsfull`, `geometry` (shapely geometry or `None`). This is the `parcels` input `cluster_parcels_by_street` (Task 2) expects.
  - `fetch_roadways(base_url: str = PARCELS_MAPSERVER_URL) -> list[dict]` — each item has keys `roadname`, `geometry`. This is the `roadways` input `cluster_parcels_by_street` expects.

- [ ] **Step 1: Write failing tests for fetch_parcels (single page + where-clause)**

`projects/mywater/tests/test_fetch.py`:
```python
from unittest.mock import MagicMock, patch

import pytest


def _geojson_response(features, error=None):
    mock_resp = MagicMock()
    if error is not None:
        mock_resp.json.return_value = {"error": error}
    else:
        mock_resp.json.return_value = {"type": "FeatureCollection", "features": features}
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def _feature(apn, situsstr, situsnum, situsfull, coords):
    return {
        "type": "Feature",
        "properties": {
            "APN": apn,
            "SITUSSTR": situsstr,
            "SITUSNUM": situsnum,
            "SITUSFULL": situsfull,
        },
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


def test_fetch_parcels_parses_single_page():
    from precompute.fetch import fetch_parcels

    coords = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    page = [_feature("APN1", "MAIN ST", "100", "CLEARLAKE OAKS", coords)]
    with patch("precompute.fetch.requests.get", return_value=_geojson_response(page)) as mock_get:
        result = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 1
    assert result[0]["apn"] == "APN1"
    assert result[0]["situsstr"] == "MAIN ST"
    assert result[0]["geometry"] is not None
    mock_get.assert_called_once()
    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["where"] == "SITUSFULL LIKE '%CLEARLAKE OAKS%'"
    assert called_params["outSR"] == 4326
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd projects/mywater && python -m pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'precompute.fetch'`

- [ ] **Step 3: Implement fetch.py with _query_all_features and fetch_parcels**

`projects/mywater/precompute/fetch.py`:
```python
import requests
from shapely.geometry import shape

PARCELS_MAPSERVER_URL = "https://gis.lakecountyca.gov/server/rest/services/Parcels/MapServer"
PAGE_SIZE = 1000


def _query_all_features(layer_url, where, out_fields):
    features = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "geojson",
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
        }
        resp = requests.get(f"{layer_url}/query", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"ArcGIS query error: {data['error']}")
        page_features = data.get("features", [])
        features.extend(page_features)
        if len(page_features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return features


def fetch_parcels(community_name, base_url=PARCELS_MAPSERVER_URL):
    where = f"SITUSFULL LIKE '%{community_name}%'"
    features = _query_all_features(f"{base_url}/0", where, "APN,SITUSSTR,SITUSNUM,SITUSFULL")
    records = []
    for feat in features:
        props = feat["properties"]
        geom = shape(feat["geometry"]) if feat.get("geometry") else None
        records.append(
            {
                "apn": props.get("APN"),
                "situsstr": (props.get("SITUSSTR") or "").strip(),
                "situsnum": props.get("SITUSNUM"),
                "situsfull": props.get("SITUSFULL"),
                "geometry": geom,
            }
        )
    return records
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd projects/mywater && python -m pytest tests/test_fetch.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Write failing tests for pagination, fetch_roadways, and error handling**

Append to `projects/mywater/tests/test_fetch.py`:
```python
def test_fetch_parcels_paginates_full_pages():
    from precompute.fetch import fetch_parcels

    coords = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    full_page = [_feature(f"APN{i}", "MAIN ST", str(i), "CLEARLAKE OAKS", coords) for i in range(1000)]
    partial_page = [_feature("APN_LAST", "MAIN ST", "9999", "CLEARLAKE OAKS", coords)]
    responses = [_geojson_response(full_page), _geojson_response(partial_page)]
    with patch("precompute.fetch.requests.get", side_effect=responses) as mock_get:
        result = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 1001
    assert mock_get.call_count == 2
    second_call_params = mock_get.call_args_list[1].kwargs["params"]
    assert second_call_params["resultOffset"] == 1000


def test_fetch_roadways_parses_linestring_features():
    from precompute.fetch import fetch_roadways

    feature = {
        "type": "Feature",
        "properties": {"ROADNAME": "MAIN ST"},
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]},
    }
    with patch("precompute.fetch.requests.get", return_value=_geojson_response([feature])):
        result = fetch_roadways()

    assert len(result) == 1
    assert result[0]["roadname"] == "MAIN ST"
    assert result[0]["geometry"].length == 10


def test_fetch_parcels_raises_on_arcgis_error_payload():
    from precompute.fetch import fetch_parcels

    with patch(
        "precompute.fetch.requests.get",
        return_value=_geojson_response([], error={"code": 400, "message": "bad request"}),
    ):
        with pytest.raises(RuntimeError, match="ArcGIS query error"):
            fetch_parcels("CLEARLAKE OAKS")
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd projects/mywater && python -m pytest tests/test_fetch.py -v`
Expected: FAIL — `fetch_roadways` not defined; pagination test fails against single-request implementation

- [ ] **Step 7: Implement fetch_roadways and confirm pagination**

Append to `projects/mywater/precompute/fetch.py`:
```python
def fetch_roadways(base_url=PARCELS_MAPSERVER_URL):
    features = _query_all_features(f"{base_url}/1", "1=1", "ROADNAME")
    records = []
    for feat in features:
        props = feat["properties"]
        geom = shape(feat["geometry"]) if feat.get("geometry") else None
        records.append({"roadname": (props.get("ROADNAME") or "").strip(), "geometry": geom})
    return records
```

(Pagination is already handled by `_query_all_features` from Step 3 — no changes needed there.)

- [ ] **Step 8: Run all fetch tests to verify they pass**

Run: `cd projects/mywater && python -m pytest tests/test_fetch.py -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Commit**

```bash
git add projects/mywater/precompute/fetch.py projects/mywater/tests/test_fetch.py
git commit -m "mywater: Lake County ArcGIS REST fetch client"
```

---

### Task 4: Load clusters and parcels into the database

**Files:**
- Modify: `projects/mywater/precompute/load.py`
- Test: `projects/mywater/tests/test_load.py`

**Interfaces:**
- Consumes: `precompute.load.connect`, `precompute.load.init_schema` (Task 1); the `clusters` list shape produced by `precompute.cluster.cluster_parcels_by_street` (Task 2) — each cluster dict has `street_name`, `geometry`, `centroid_lat`, `centroid_lng`, `parcel_count`, `members` (list of parcel dicts with `apn`, `situsstr`, `situsnum`, `geometry`).
- Produces: `precompute.load.load_clusters_and_parcels(conn: sqlite3.Connection, clusters: list[dict]) -> None`. Later consumed by `run.py` (Task 5).

- [ ] **Step 1: Write failing test for load_clusters_and_parcels**

Append to `projects/mywater/tests/test_load.py`:
```python
from shapely.geometry import Polygon


def _square(cx, cy, size=0.2):
    return Polygon(
        [
            (cx - size / 2, cy - size / 2),
            (cx + size / 2, cy - size / 2),
            (cx + size / 2, cy + size / 2),
            (cx - size / 2, cy + size / 2),
        ]
    )


def test_load_clusters_and_parcels_round_trip(conn):
    from precompute.load import load_clusters_and_parcels

    clusters = [
        {
            "street_name": "MAIN ST",
            "geometry": _square(2, 0),
            "centroid_lat": 0.0,
            "centroid_lng": 2.0,
            "parcel_count": 2,
            "members": [
                {"apn": "A", "situsstr": "MAIN ST", "situsnum": "100", "geometry": _square(1, 0)},
                {"apn": "B", "situsstr": "MAIN ST", "situsnum": "200", "geometry": _square(3, 0)},
            ],
        }
    ]
    load_clusters_and_parcels(conn, clusters)

    cluster_rows = conn.execute(
        "SELECT id, street_name, parcel_count FROM parcel_clusters"
    ).fetchall()
    assert cluster_rows == [(1, "MAIN ST", 2)]

    parcel_rows = conn.execute("SELECT apn, cluster_id FROM parcels ORDER BY apn").fetchall()
    assert parcel_rows == [("A", 1), ("B", 1)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd projects/mywater && python -m pytest tests/test_load.py -v`
Expected: FAIL — `load_clusters_and_parcels` not defined

- [ ] **Step 3: Implement load_clusters_and_parcels**

Append to `projects/mywater/precompute/load.py`:
```python
from shapely.geometry import MultiPolygon


def _to_multipolygon_wkt(geom):
    if geom.geom_type == "Polygon":
        geom = MultiPolygon([geom])
    return geom.wkt


def load_clusters_and_parcels(conn, clusters):
    cur = conn.cursor()
    for cluster in clusters:
        cur.execute(
            """
            INSERT INTO parcel_clusters (street_name, centroid_lat, centroid_lng, parcel_count, geometry)
            VALUES (?, ?, ?, ?, ST_GeomFromText(?, 4326))
            """,
            (
                cluster["street_name"],
                cluster["centroid_lat"],
                cluster["centroid_lng"],
                cluster["parcel_count"],
                _to_multipolygon_wkt(cluster["geometry"]),
            ),
        )
        cluster_id = cur.lastrowid
        for parcel in cluster["members"]:
            centroid = parcel["geometry"].centroid
            cur.execute(
                """
                INSERT INTO parcels (apn, situsstr, situsnum, cluster_id, centroid_lat, centroid_lng, geometry)
                VALUES (?, ?, ?, ?, ?, ?, ST_GeomFromText(?, 4326))
                """,
                (
                    parcel["apn"],
                    parcel["situsstr"],
                    parcel["situsnum"],
                    cluster_id,
                    centroid.y,
                    centroid.x,
                    _to_multipolygon_wkt(parcel["geometry"]),
                ),
            )
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd projects/mywater && python -m pytest tests/test_load.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add projects/mywater/precompute/load.py projects/mywater/tests/test_load.py
git commit -m "mywater: load clusters and parcels into SpatiaLite"
```

---

### Task 5: CLI entrypoint and live end-to-end run

**Files:**
- Create: `projects/mywater/precompute/run.py`

**Interfaces:**
- Consumes: `precompute.fetch.fetch_parcels`, `precompute.fetch.fetch_roadways` (Task 3); `precompute.cluster.cluster_parcels_by_street`, `MIN_CLUSTER_SIZE`, `MAX_CLUSTER_SIZE` (Task 2); `precompute.load.connect`, `precompute.load.init_schema`, `precompute.load.load_clusters_and_parcels` (Tasks 1 and 4).
- Produces: a runnable script, `precompute/run.py`, and (when run) the file `projects/mywater/mywater.db`. No other module depends on `run.py`'s internals — it's the pipeline's entrypoint, not a library.

- [ ] **Step 1: Implement run.py**

`projects/mywater/precompute/run.py`:
```python
import argparse
from pathlib import Path

from precompute.cluster import MAX_CLUSTER_SIZE, MIN_CLUSTER_SIZE, cluster_parcels_by_street
from precompute.fetch import fetch_parcels, fetch_roadways
from precompute.load import connect, init_schema, load_clusters_and_parcels

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path(__file__).parent.parent / "mywater.db"
COMMUNITY_NAME = "CLEARLAKE OAKS"


def main(db_path=DEFAULT_DB_PATH):
    print(f"Fetching parcels for community '{COMMUNITY_NAME}'...")
    parcels = fetch_parcels(COMMUNITY_NAME)
    print(f"Fetched {len(parcels)} parcels.")

    print("Fetching roadway centerlines...")
    roadways = fetch_roadways()
    print(f"Fetched {len(roadways)} roadway segments.")

    clusters, excluded, outlier_indices = cluster_parcels_by_street(parcels, roadways)
    print(f"Built {len(clusters)} clusters from {len(parcels) - len(excluded)} parcels.")

    if excluded:
        print(f"WARNING: excluded {len(excluded)} parcels with no geometry or street name: {excluded}")

    if outlier_indices:
        print(
            f"WARNING: {len(outlier_indices)} clusters outside the "
            f"{MIN_CLUSTER_SIZE}-{MAX_CLUSTER_SIZE} parcel target range, flagged for manual review:"
        )
        for i in outlier_indices:
            c = clusters[i]
            print(f"  - {c['street_name']}: {c['parcel_count']} parcels")

    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    conn = connect(str(db_path))
    init_schema(conn, SCHEMA_PATH)
    load_clusters_and_parcels(conn, clusters)
    conn.close()
    print(
        f"Wrote {len(clusters)} clusters and "
        f"{sum(c['parcel_count'] for c in clusters)} parcels to {db_path}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the mywater parcel/cluster database.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    main(db_path=args.db_path)
```

- [ ] **Step 2: Run the pipeline against live data**

```bash
cd projects/mywater
source .venv/bin/activate
python -m precompute.run
```

- [ ] **Step 3: Manually verify the output**

Check the printed summary: parcel count should be in the hundreds (matching "~800 houses in the Keys" plus the broader Clearlake Oaks community), cluster count roughly parcel_count / 8, and review any printed warnings — a handful of outlier clusters or excluded parcels is expected and fine (e.g. short cul-de-sacs, parcels with malformed data); a large fraction of either signals a real bug worth investigating before moving on to the backend plan.

Then spot-check the database directly:
```bash
python3 -c "
from precompute.load import connect
conn = connect('mywater.db')
print('clusters:', conn.execute('SELECT COUNT(*) FROM parcel_clusters').fetchone()[0])
print('parcels:', conn.execute('SELECT COUNT(*) FROM parcels').fetchone()[0])
print(conn.execute('SELECT street_name, parcel_count FROM parcel_clusters LIMIT 5').fetchall())
"
```

- [ ] **Step 4: Commit**

```bash
git add projects/mywater/precompute/run.py
git commit -m "mywater: precompute pipeline CLI entrypoint"
```

`mywater.db` itself is git-ignored (Task 1's `.gitignore`) — it's a generated artifact, regenerated by running `python -m precompute.run` whenever Lake County's parcel data changes.

---

## Self-Review Notes

- **Spec coverage**: Architecture & Stack (fetch/cluster/load split, no GeoPandas) — Tasks 1-5. Anonymization Pipeline's four steps (fetch, cluster, load, sanity check) — Tasks 3, 2, 4, and the outlier/exclusion warnings in Task 5 respectively. Testing/Verification's "automated tests for clustering correctness, parcel/cluster mutual exclusivity... " — Task 2 covers clustering correctness and exclusion; the `cluster_id NOT NULL REFERENCES parcel_clusters(id)` constraint in Task 1's schema enforces every loaded parcel belongs to exactly one cluster structurally, backed by Task 4's round-trip test.
- **Placeholder scan**: none found — every step has complete code or a concrete shell command.
- **Type consistency**: `parcels` list-of-dict shape (`apn`, `situsstr`, `situsnum`, `situsfull`, `geometry`) is identical across `fetch.py` (Task 3, producer) and `cluster.py` (Task 2, consumer). `clusters` list-of-dict shape (`street_name`, `geometry`, `centroid_lat`, `centroid_lng`, `parcel_count`, `members`) is identical across `cluster.py` (Task 2, producer) and `load.py` (Task 4, consumer) and matches the test fixture in Task 4 Step 1.

This plan produces the `mywater.db` file (schema: `parcels`, `parcel_clusters`) that the next plan — the backend API — reads from.
