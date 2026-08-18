# mywater Backend API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI backend that lets residents submit water-quality reports (exact-parcel or anonymized-cluster location) and serves the report/parcel/cluster data as GeoJSON — the second of three mywater components. This plan is JSON/GeoJSON API only; HTML templates, Leaflet map rendering, HTMX partial-swap UI, and the About/FAQ anonymization page are a separate, later frontend plan that consumes this API.

**Architecture:** A FastAPI app with two SQLite databases: `mywater.db` (precompute-owned — `parcels`/`parcel_clusters`, read-only from this app) and `mywater_app.db` (this app's own `reports`/`submission_log`, created and owned here). Each request attaches `mywater.db` onto the app-db connection via SQLite's `ATTACH DATABASE` for cross-file joins (e.g. resolving a report's cluster to its centroid). Report submission validates via a Pydantic model, checks a lightweight IP/cookie rate limit, optionally uploads a photo to Cloudflare R2, then inserts. Two GeoJSON-serving endpoint groups (parcels/clusters, reports) let a future frontend render the map without any additional backend work.

**Tech Stack:** FastAPI, Pydantic, `python-multipart` (form/file parsing), `boto3` (R2's S3-compatible API), SQLite + SpatiaLite (reusing `precompute/load.py`'s connection helper), pytest + FastAPI's `TestClient`.

## Global Constraints

- Stack: FastAPI, following `projects/template-code` conventions. (Jinja2/HTMX/static templates are explicitly out of scope for this plan — deferred to the frontend plan.)
- No accounts, no CAPTCHA, no moderation queue — reports publish immediately.
- Rate limit: 5 reports/day per IP or cookie, whichever is stricter (`RATE_LIMIT_PER_DAY` env var, default `5`).
- Photo constraints: max 5MB, `image/jpeg`/`image/png`/`image/heic` allowlist only, validated server-side regardless of client-side checks.
- Free-text cap: 500 characters.
- No raw lat/lng is ever stored in `reports` — every report resolves to exactly one of `parcel_id` (non-obscured) or `cluster_id` (obscured), never both, never neither.
- IP address read from Cloudflare's `CF-Connecting-IP` header, falling back to the raw connection address for local dev.
- Photos upload to Cloudflare R2; the database stores only the resulting object URL.
- **Two-file DB split** (spec revision, 2026-08-18): `mywater.db` (precompute-owned: `parcels`, `parcel_clusters`) and `mywater_app.db` (this app's own: `reports`, `submission_log`). This app must never write to `parcels`/`parcel_clusters` — only read them via an attached, separate database file. Precompute's destructive rebuild (`db_path.unlink()` on every run) can therefore never touch report data.
- Obscured reports must never expose parcel-level identity (`parcel_id`, `apn`, parcel geometry) in any API response — only the cluster's centroid and street name.
- Obscured reports may only reference a cluster where `anonymization_safe = 1` (set by the precompute pipeline; `0` means the cluster has fewer than `MIN_CLUSTER_SIZE` (6) parcels and offering it would not actually anonymize the reporter).
- Quality-report and event-report validation rules (not fully specified in the design spec; decided during planning — flag to the user if these should change): quality reports require at least one of a rating field (`taste`/`smell`/`color`/`pressure`) or non-empty `free_text`, and must not set `event_subtype`/`ongoing`. Event reports require `event_subtype`, and must not set any quality rating field.

---

## File Structure

```
projects/mywater/
  db.py                    -- app-db schema init, per-request connection (attaches mywater.db)
  db_app_schema.sql        -- DDL for reports + submission_log (mywater_app.db)
  main.py                  -- FastAPI app, lifespan (schema init), health check, router mounting
  models.py                -- ReportCreate Pydantic model + validation rules
  rate_limit.py            -- IP/cookie hashing + submission_log threshold checks
  photos.py                -- photo validation + R2 (S3-compatible) upload
  routers/
    __init__.py
    reports.py              -- POST /api/reports, GET /api/reports.geojson
    parcels.py               -- GET /api/parcels.geojson, GET /api/clusters.geojson
  requirements.txt          -- extended with fastapi, uvicorn, boto3, etc.
  .env.example              -- extended with R2/rate-limit config
  .gitignore                -- extended with mywater_app.db
  tests/
    conftest.py              -- shared fixtures: temp parcels.db + app.db, FastAPI TestClient (introduced in Task 5)
    test_db.py
    test_models.py
    test_rate_limit.py
    test_photos.py
    test_reports_api.py
    test_parcels_api.py
```

---

### Task 1: App scaffolding — two-database setup, health check

**Files:**
- Modify: `projects/mywater/requirements.txt`
- Modify: `projects/mywater/.gitignore`
- Create: `projects/mywater/.env.example`
- Create: `projects/mywater/db_app_schema.sql`
- Create: `projects/mywater/db.py`
- Create: `projects/mywater/main.py`
- Create: `projects/mywater/routers/__init__.py`
- Test: `projects/mywater/tests/test_db.py`

**Interfaces:**
- Produces: `db.init_app_db(app_db_path: str | Path = DEFAULT_APP_DB_PATH) -> None`, `db.get_connection(app_db_path=DEFAULT_APP_DB_PATH, parcels_db_path=DEFAULT_PARCELS_DB_PATH) -> sqlite3.Connection` (SpatiaLite loaded, `parcels_db` schema attached read-write-capable at the SQLite level but never written to by this app's own code), `db.get_db()` (FastAPI dependency generator wrapping `get_connection`, closes on teardown). `db.DEFAULT_APP_DB_PATH`, `db.DEFAULT_PARCELS_DB_PATH`. `main.app` (the FastAPI instance, importable by later tasks' routers and tests).

- [ ] **Step 1: Extend requirements.txt**

`projects/mywater/requirements.txt` (replace entire file):
```
requests
shapely
pytest
fastapi
uvicorn[standard]
python-multipart
python-dotenv
boto3
httpx
```

- [ ] **Step 2: Extend .gitignore**

`projects/mywater/.gitignore` (replace entire file):
```
__pycache__/
*.pyc
mywater.db
mywater_app.db
.venv/
```

- [ ] **Step 3: Create .env.example**

`projects/mywater/.env.example`:
```
# Rate limiting
RATE_LIMIT_PER_DAY=5
RATE_LIMIT_PEPPER=change-me-to-a-random-string

# Cloudflare R2 (S3-compatible object storage) for photo uploads
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
R2_PUBLIC_BASE_URL=
```

- [ ] **Step 4: Write the app database schema**

`projects/mywater/db_app_schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL CHECK (report_type IN ('event', 'quality')),
    obscured INTEGER NOT NULL CHECK (obscured IN (0, 1)),
    parcel_id INTEGER,
    cluster_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    free_text TEXT,
    photo_url TEXT,
    taste TEXT CHECK (taste IN ('good', 'off', 'bad')),
    smell TEXT CHECK (smell IN ('good', 'off', 'bad')),
    color TEXT CHECK (color IN ('good', 'off', 'bad')),
    pressure TEXT CHECK (pressure IN ('good', 'off', 'bad')),
    event_subtype TEXT CHECK (event_subtype IN ('main_break', 'outage', 'boil_notice', 'other')),
    ongoing INTEGER CHECK (ongoing IN (0, 1)),
    CHECK (length(free_text) <= 500),
    CHECK (
        (obscured = 0 AND parcel_id IS NOT NULL AND cluster_id IS NULL)
        OR (obscured = 1 AND cluster_id IS NOT NULL AND parcel_id IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at);

CREATE TABLE IF NOT EXISTS submission_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_hash TEXT NOT NULL,
    cookie_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_submission_log_ip_hash_created_at ON submission_log(ip_hash, created_at);
CREATE INDEX IF NOT EXISTS idx_submission_log_cookie_id_created_at ON submission_log(cookie_id, created_at);
```

Note: `parcel_id`/`cluster_id` are NOT declared with `REFERENCES` — SQLite cannot enforce a foreign key across an `ATTACH`ed database file. Validity is checked at the application layer (Task 5).

- [ ] **Step 5: Write the failing test for init_app_db and get_connection**

`projects/mywater/tests/test_db.py`:
```python
from pathlib import Path

import pytest


def test_init_app_db_creates_expected_tables(tmp_path):
    from db import init_app_db

    db_path = tmp_path / "mywater_app.db"
    init_app_db(db_path)

    import sqlite3

    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert {"reports", "submission_log"} <= tables


def test_get_connection_attaches_parcels_db_read_access(tmp_path):
    from db import get_connection, init_app_db
    from precompute.load import connect as spatialite_connect
    from precompute.load import init_schema as init_parcels_schema

    app_db_path = tmp_path / "mywater_app.db"
    init_app_db(app_db_path)

    parcels_db_path = tmp_path / "mywater.db"
    schema_path = Path(__file__).parent.parent / "precompute" / "schema.sql"
    parcels_conn = spatialite_connect(str(parcels_db_path))
    init_parcels_schema(parcels_conn, schema_path)
    parcels_conn.close()

    conn = get_connection(app_db_path=app_db_path, parcels_db_path=parcels_db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    attached_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM parcels_db.sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "reports" in tables
    assert {"parcels", "parcel_clusters"} <= attached_tables
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 7: Implement db.py**

`projects/mywater/db.py`:
```python
from pathlib import Path

from precompute.load import connect as _connect_spatialite

APP_SCHEMA_PATH = Path(__file__).parent / "db_app_schema.sql"
DEFAULT_APP_DB_PATH = Path(__file__).parent / "mywater_app.db"
DEFAULT_PARCELS_DB_PATH = Path(__file__).parent / "mywater.db"


def init_app_db(app_db_path=DEFAULT_APP_DB_PATH):
    conn = _connect_spatialite(str(app_db_path))
    with open(APP_SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def get_connection(app_db_path=DEFAULT_APP_DB_PATH, parcels_db_path=DEFAULT_PARCELS_DB_PATH):
    conn = _connect_spatialite(str(app_db_path))
    conn.execute("ATTACH DATABASE ? AS parcels_db", (str(parcels_db_path),))
    return conn


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_db.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Write the failing test for the FastAPI app's health check**

Append to `projects/mywater/tests/test_db.py`:
```python
def test_health_check_returns_ok():
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 10: Run test to verify it fails**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 11: Implement main.py and routers/__init__.py**

`projects/mywater/routers/__init__.py`: (empty file)

`projects/mywater/main.py`:
```python
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402

from db import init_app_db  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_app_db()
    yield


app = FastAPI(title="mywater", lifespan=lifespan)


@app.get("/")
def health():
    return {"status": "ok"}
```

- [ ] **Step 12: Run all Task 1 tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_db.py -v`
Expected: PASS (3 tests)

- [ ] **Step 13: Commit**

```bash
git add projects/mywater/requirements.txt projects/mywater/.gitignore projects/mywater/.env.example \
  projects/mywater/db_app_schema.sql projects/mywater/db.py projects/mywater/main.py \
  projects/mywater/routers/__init__.py projects/mywater/tests/test_db.py
git commit -m "mywater: backend app scaffolding, two-database setup"
```

---

### Task 2: Report validation model

**Files:**
- Create: `projects/mywater/models.py`
- Test: `projects/mywater/tests/test_models.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure Pydantic, no I/O).
- Produces: `models.ReportCreate` (Pydantic `BaseModel`) with fields `report_type: str`, `obscured: bool`, `parcel_id: int | None`, `cluster_id: int | None`, `free_text: str | None`, `taste: str | None`, `smell: str | None`, `color: str | None`, `pressure: str | None`, `event_subtype: str | None`, `ongoing: bool | None`. Raises `pydantic.ValidationError` (via `ValueError` inside validators) on invalid combinations. Consumed directly by Task 5's endpoint.

- [ ] **Step 1: Write failing tests for the mutual-exclusivity and type-specific validation rules**

`projects/mywater/tests/test_models.py`:
```python
import pytest
from pydantic import ValidationError

from models import ReportCreate


def test_valid_non_obscured_event_report():
    report = ReportCreate(
        report_type="event",
        obscured=False,
        parcel_id=1,
        event_subtype="main_break",
    )
    assert report.parcel_id == 1
    assert report.cluster_id is None


def test_valid_obscured_quality_report():
    report = ReportCreate(
        report_type="quality",
        obscured=True,
        cluster_id=5,
        taste="bad",
    )
    assert report.cluster_id == 5
    assert report.parcel_id is None


def test_rejects_invalid_report_type():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="bogus", obscured=False, parcel_id=1, event_subtype="outage")


def test_rejects_non_obscured_report_without_parcel_id():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="event", obscured=False, event_subtype="outage")


def test_rejects_obscured_report_with_parcel_id_set():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="event",
            obscured=True,
            cluster_id=5,
            parcel_id=1,
            event_subtype="outage",
        )


def test_rejects_non_obscured_report_with_cluster_id_set():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="event",
            obscured=False,
            parcel_id=1,
            cluster_id=5,
            event_subtype="outage",
        )


def test_rejects_free_text_over_500_chars():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="event",
            obscured=False,
            parcel_id=1,
            event_subtype="outage",
            free_text="x" * 501,
        )


def test_rejects_invalid_quality_rating_value():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="quality", obscured=True, cluster_id=5, taste="terrible")


def test_rejects_event_report_missing_event_subtype():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="event", obscured=False, parcel_id=1)


def test_rejects_event_report_with_quality_field_set():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="event",
            obscured=False,
            parcel_id=1,
            event_subtype="outage",
            taste="bad",
        )


def test_rejects_quality_report_with_event_field_set():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="quality",
            obscured=True,
            cluster_id=5,
            taste="bad",
            event_subtype="outage",
        )


def test_rejects_quality_report_with_no_rating_and_no_text():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="quality", obscured=True, cluster_id=5)


def test_accepts_quality_report_with_only_free_text():
    report = ReportCreate(
        report_type="quality", obscured=True, cluster_id=5, free_text="tastes off today"
    )
    assert report.free_text == "tastes off today"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 3: Implement models.py**

`projects/mywater/models.py`:
```python
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

VALID_REPORT_TYPES = {"event", "quality"}
VALID_QUALITY_RATINGS = {"good", "off", "bad"}
VALID_EVENT_SUBTYPES = {"main_break", "outage", "boil_notice", "other"}
FREE_TEXT_MAX_LENGTH = 500


class ReportCreate(BaseModel):
    report_type: str
    obscured: bool
    parcel_id: Optional[int] = None
    cluster_id: Optional[int] = None
    free_text: Optional[str] = None
    taste: Optional[str] = None
    smell: Optional[str] = None
    color: Optional[str] = None
    pressure: Optional[str] = None
    event_subtype: Optional[str] = None
    ongoing: Optional[bool] = None

    @field_validator("report_type")
    @classmethod
    def validate_report_type(cls, v):
        if v not in VALID_REPORT_TYPES:
            raise ValueError(f"report_type must be one of {sorted(VALID_REPORT_TYPES)}")
        return v

    @field_validator("free_text")
    @classmethod
    def validate_free_text_length(cls, v):
        if v is not None and len(v) > FREE_TEXT_MAX_LENGTH:
            raise ValueError(f"free_text must be at most {FREE_TEXT_MAX_LENGTH} characters")
        return v

    @field_validator("taste", "smell", "color", "pressure")
    @classmethod
    def validate_quality_rating(cls, v):
        if v is not None and v not in VALID_QUALITY_RATINGS:
            raise ValueError(f"rating must be one of {sorted(VALID_QUALITY_RATINGS)}")
        return v

    @field_validator("event_subtype")
    @classmethod
    def validate_event_subtype(cls, v):
        if v is not None and v not in VALID_EVENT_SUBTYPES:
            raise ValueError(f"event_subtype must be one of {sorted(VALID_EVENT_SUBTYPES)}")
        return v

    @model_validator(mode="after")
    def validate_location_exclusivity(self):
        if self.obscured:
            if self.cluster_id is None or self.parcel_id is not None:
                raise ValueError("obscured reports must set cluster_id and leave parcel_id unset")
        else:
            if self.parcel_id is None or self.cluster_id is not None:
                raise ValueError("non-obscured reports must set parcel_id and leave cluster_id unset")
        return self

    @model_validator(mode="after")
    def validate_type_specific_fields(self):
        if self.report_type == "event":
            if self.event_subtype is None:
                raise ValueError("event reports require event_subtype")
            if any([self.taste, self.smell, self.color, self.pressure]):
                raise ValueError("event reports must not set quality rating fields")
        elif self.report_type == "quality":
            if self.event_subtype is not None or self.ongoing is not None:
                raise ValueError("quality reports must not set event_subtype or ongoing")
            has_rating = any([self.taste, self.smell, self.color, self.pressure])
            has_text = bool(self.free_text and self.free_text.strip())
            if not has_rating and not has_text:
                raise ValueError("quality reports need at least one rating or free_text")
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_models.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add projects/mywater/models.py projects/mywater/tests/test_models.py
git commit -m "mywater: report validation model"
```

---

### Task 3: Rate limiting

**Files:**
- Create: `projects/mywater/rate_limit.py`
- Test: `projects/mywater/tests/test_rate_limit.py`

**Interfaces:**
- Consumes: `db.init_app_db`, `precompute.load.connect` (Task 1) — for building a test connection with the `submission_log` table.
- Produces: `rate_limit.hash_identifier(value: str) -> str`, `rate_limit.is_rate_limited(conn, ip_hash: str, cookie_id: str, limit: int | None = None) -> bool`, `rate_limit.record_submission(conn, ip_hash: str, cookie_id: str) -> None`, `rate_limit.RATE_LIMIT_PER_DAY: int`. Consumed by Task 5's endpoint.

- [ ] **Step 1: Write failing tests for the threshold logic**

`projects/mywater/tests/test_rate_limit.py`:
```python
from pathlib import Path

import pytest

from db import init_app_db
from precompute.load import connect as spatialite_connect


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "mywater_app.db"
    init_app_db(db_path)
    connection = spatialite_connect(str(db_path))
    yield connection
    connection.close()


def test_hash_identifier_is_deterministic_and_not_plaintext():
    from rate_limit import hash_identifier

    h1 = hash_identifier("1.2.3.4")
    h2 = hash_identifier("1.2.3.4")
    assert h1 == h2
    assert h1 != "1.2.3.4"


def test_hash_identifier_differs_for_different_inputs():
    from rate_limit import hash_identifier

    assert hash_identifier("1.2.3.4") != hash_identifier("5.6.7.8")


def test_is_rate_limited_false_when_under_threshold(conn):
    from rate_limit import is_rate_limited, record_submission

    ip_hash, cookie_id = "iphash1", "cookie1"
    for _ in range(4):
        record_submission(conn, ip_hash, cookie_id)
    assert is_rate_limited(conn, ip_hash, cookie_id, limit=5) is False


def test_is_rate_limited_true_when_ip_hits_threshold(conn):
    from rate_limit import is_rate_limited, record_submission

    ip_hash, cookie_id = "iphash1", "cookie1"
    for _ in range(5):
        record_submission(conn, ip_hash, cookie_id)
    assert is_rate_limited(conn, ip_hash, cookie_id, limit=5) is True


def test_is_rate_limited_true_when_cookie_hits_threshold_even_if_ip_differs(conn):
    from rate_limit import is_rate_limited, record_submission

    cookie_id = "shared_cookie"
    for i in range(5):
        record_submission(conn, f"iphash{i}", cookie_id)
    assert is_rate_limited(conn, "some_new_iphash", cookie_id, limit=5) is True


def test_is_rate_limited_ignores_entries_older_than_24_hours(conn):
    from rate_limit import is_rate_limited

    ip_hash, cookie_id = "iphash1", "cookie1"
    old_timestamp = "2000-01-01T00:00:00"
    for _ in range(5):
        conn.execute(
            "INSERT INTO submission_log (ip_hash, cookie_id, created_at) VALUES (?, ?, ?)",
            (ip_hash, cookie_id, old_timestamp),
        )
    conn.commit()
    assert is_rate_limited(conn, ip_hash, cookie_id, limit=5) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_rate_limit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rate_limit'`

- [ ] **Step 3: Implement rate_limit.py**

`projects/mywater/rate_limit.py`:
```python
import hashlib
import os
from datetime import datetime, timedelta, timezone

RATE_LIMIT_PER_DAY = int(os.environ.get("RATE_LIMIT_PER_DAY", "5"))
_RATE_LIMIT_PEPPER = os.environ.get("RATE_LIMIT_PEPPER", "")


def hash_identifier(value):
    return hashlib.sha256((_RATE_LIMIT_PEPPER + value).encode("utf-8")).hexdigest()


def _count_recent(conn, column, value, since_iso):
    row = conn.execute(
        f"SELECT COUNT(*) FROM submission_log WHERE {column} = ? AND created_at >= ?",
        (value, since_iso),
    ).fetchone()
    return row[0]


def is_rate_limited(conn, ip_hash, cookie_id, limit=None):
    if limit is None:
        limit = RATE_LIMIT_PER_DAY
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    ip_count = _count_recent(conn, "ip_hash", ip_hash, since)
    cookie_count = _count_recent(conn, "cookie_id", cookie_id, since)
    return ip_count >= limit or cookie_count >= limit


def record_submission(conn, ip_hash, cookie_id):
    conn.execute(
        "INSERT INTO submission_log (ip_hash, cookie_id) VALUES (?, ?)",
        (ip_hash, cookie_id),
    )
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_rate_limit.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add projects/mywater/rate_limit.py projects/mywater/tests/test_rate_limit.py
git commit -m "mywater: rate limiting"
```

---

### Task 4: Photo validation and R2 upload

**Files:**
- Create: `projects/mywater/photos.py`
- Test: `projects/mywater/tests/test_photos.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `photos.MAX_PHOTO_SIZE_BYTES: int`, `photos.ALLOWED_CONTENT_TYPES: dict[str, str]`, `photos.PhotoValidationError(ValueError)`, `photos.validate_photo(content: bytes, content_type: str) -> None` (raises `PhotoValidationError`), `photos.upload_photo(content: bytes, content_type: str) -> str` (returns the public URL). Consumed by Task 5's endpoint.

- [ ] **Step 1: Write failing tests for validate_photo**

`projects/mywater/tests/test_photos.py`:
```python
import pytest

from photos import MAX_PHOTO_SIZE_BYTES, PhotoValidationError, validate_photo


def test_validate_photo_accepts_small_jpeg():
    validate_photo(b"x" * 100, "image/jpeg")


def test_validate_photo_rejects_disallowed_content_type():
    with pytest.raises(PhotoValidationError):
        validate_photo(b"x" * 100, "image/gif")


def test_validate_photo_rejects_oversized_content():
    with pytest.raises(PhotoValidationError):
        validate_photo(b"x" * (MAX_PHOTO_SIZE_BYTES + 1), "image/jpeg")


def test_validate_photo_accepts_content_at_exact_size_limit():
    validate_photo(b"x" * MAX_PHOTO_SIZE_BYTES, "image/png")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_photos.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'photos'`

- [ ] **Step 3: Implement validate_photo**

`projects/mywater/photos.py`:
```python
import os
import uuid

import boto3

MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
}


class PhotoValidationError(ValueError):
    pass


def validate_photo(content, content_type):
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise PhotoValidationError(
            f"unsupported photo type '{content_type}'; allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
        )
    if len(content) > MAX_PHOTO_SIZE_BYTES:
        raise PhotoValidationError(
            f"photo exceeds {MAX_PHOTO_SIZE_BYTES} byte limit ({len(content)} bytes)"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_photos.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Write failing test for upload_photo (mocked R2 client)**

Append to `projects/mywater/tests/test_photos.py`:
```python
from unittest.mock import MagicMock, patch


def test_upload_photo_validates_before_uploading():
    from photos import upload_photo

    with pytest.raises(PhotoValidationError):
        upload_photo(b"x" * 100, "image/gif")


@patch.dict(
    "os.environ",
    {
        "R2_ACCOUNT_ID": "test-account",
        "R2_ACCESS_KEY_ID": "test-key",
        "R2_SECRET_ACCESS_KEY": "test-secret",
        "R2_BUCKET_NAME": "test-bucket",
        "R2_PUBLIC_BASE_URL": "https://photos.example.com",
    },
)
def test_upload_photo_puts_object_and_returns_public_url():
    from photos import upload_photo

    mock_client = MagicMock()
    with patch("photos.boto3.client", return_value=mock_client) as mock_boto_client:
        url = upload_photo(b"fake-jpeg-bytes", "image/jpeg")

    mock_boto_client.assert_called_once()
    call_kwargs = mock_boto_client.call_args.kwargs
    assert call_kwargs["endpoint_url"] == "https://test-account.r2.cloudflarestorage.com"

    mock_client.put_object.assert_called_once()
    put_kwargs = mock_client.put_object.call_args.kwargs
    assert put_kwargs["Bucket"] == "test-bucket"
    assert put_kwargs["Body"] == b"fake-jpeg-bytes"
    assert put_kwargs["ContentType"] == "image/jpeg"
    assert put_kwargs["Key"].endswith(".jpg")

    assert url == f"https://photos.example.com/{put_kwargs['Key']}"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_photos.py -v`
Expected: FAIL — `upload_photo` not defined

- [ ] **Step 7: Implement upload_photo**

Append to `projects/mywater/photos.py`:
```python
def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )


def upload_photo(content, content_type):
    validate_photo(content, content_type)
    extension = ALLOWED_CONTENT_TYPES[content_type]
    key = f"{uuid.uuid4()}.{extension}"
    bucket = os.environ["R2_BUCKET_NAME"]
    client = _r2_client()
    client.put_object(Bucket=bucket, Key=key, Body=content, ContentType=content_type)
    public_base_url = os.environ["R2_PUBLIC_BASE_URL"]
    return f"{public_base_url.rstrip('/')}/{key}"
```

- [ ] **Step 8: Run all photo tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_photos.py -v`
Expected: PASS (6 tests)

- [ ] **Step 9: Commit**

```bash
git add projects/mywater/photos.py projects/mywater/tests/test_photos.py
git commit -m "mywater: photo validation and R2 upload"
```

---

### Task 5: Report submission endpoint

**Files:**
- Create: `projects/mywater/routers/reports.py`
- Create: `projects/mywater/tests/conftest.py`
- Test: `projects/mywater/tests/test_reports_api.py`
- Modify: `projects/mywater/main.py`

**Interfaces:**
- Consumes: `db.get_db` (Task 1), `models.ReportCreate` (Task 2), `rate_limit.hash_identifier`/`is_rate_limited`/`record_submission` (Task 3), `photos.upload_photo`/`PhotoValidationError` (Task 4).
- Produces: `routers.reports.router` (a FastAPI `APIRouter`, mounted at `/api` in `main.py`) with `POST /api/reports`. Response body: `{"id": int, "report_type": str}`. Sets an `httponly` cookie named `mywater_id` for rate-limit identity. `tests/conftest.py` produces pytest fixtures `client` (a `TestClient` with `parcel_id`, `safe_cluster_id`, `unsafe_cluster_id` attributes for use by this and Task 6's tests) — consumed directly by Task 6.

- [ ] **Step 1: Write the shared test fixtures**

`projects/mywater/tests/conftest.py`:
```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from db import get_db, init_app_db
from precompute.load import connect as spatialite_connect
from precompute.load import init_schema as init_parcels_schema

PARCELS_SCHEMA_PATH = Path(__file__).parent.parent / "precompute" / "schema.sql"


def _square(cx, cy, size=0.001):
    return Polygon(
        [
            (cx - size / 2, cy - size / 2),
            (cx + size / 2, cy - size / 2),
            (cx + size / 2, cy + size / 2),
            (cx - size / 2, cy + size / 2),
        ]
    )


@pytest.fixture
def parcels_db_path(tmp_path):
    db_path = tmp_path / "mywater.db"
    conn = spatialite_connect(str(db_path))
    init_parcels_schema(conn, PARCELS_SCHEMA_PATH)

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO parcel_clusters "
        "(street_name, centroid_lat, centroid_lng, parcel_count, anonymization_safe, geometry) "
        "VALUES (?, ?, ?, ?, ?, ST_GeomFromText(?, 4326))",
        ("MAIN ST", 39.0, -122.6, 8, 1, _square(0, 0).wkt),
    )
    safe_cluster_id = cur.lastrowid
    cur.execute(
        "INSERT INTO parcel_clusters "
        "(street_name, centroid_lat, centroid_lng, parcel_count, anonymization_safe, geometry) "
        "VALUES (?, ?, ?, ?, ?, ST_GeomFromText(?, 4326))",
        ("SHORT LN", 39.01, -122.61, 2, 0, _square(1, 1).wkt),
    )
    unsafe_cluster_id = cur.lastrowid
    cur.execute(
        "INSERT INTO parcels (apn, situsstr, situsnum, cluster_id, centroid_lat, centroid_lng, geometry) "
        "VALUES (?, ?, ?, ?, ?, ?, ST_GeomFromText(?, 4326))",
        ("TEST_APN_1", "MAIN ST", "100", safe_cluster_id, 39.0, -122.6, _square(0, 0).wkt),
    )
    parcel_id = cur.lastrowid
    conn.commit()
    conn.close()
    return db_path, parcel_id, safe_cluster_id, unsafe_cluster_id


@pytest.fixture
def app_db_path(tmp_path):
    db_path = tmp_path / "mywater_app.db"
    init_app_db(db_path)
    return db_path


@pytest.fixture
def client(parcels_db_path, app_db_path):
    from main import app

    parcels_path, parcel_id, safe_cluster_id, unsafe_cluster_id = parcels_db_path

    def override_get_db():
        conn = spatialite_connect(str(app_db_path))
        conn.execute("ATTACH DATABASE ? AS parcels_db", (str(parcels_path),))
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.parcel_id = parcel_id
        test_client.safe_cluster_id = safe_cluster_id
        test_client.unsafe_cluster_id = unsafe_cluster_id
        yield test_client
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Write the failing tests for POST /api/reports**

`projects/mywater/tests/test_reports_api.py`:
```python
def test_create_non_obscured_event_report_succeeds(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "main_break",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_type"] == "event"
    assert "mywater_id" in resp.cookies


def test_create_obscured_quality_report_succeeds(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "quality",
            "obscured": "true",
            "cluster_id": str(client.safe_cluster_id),
            "taste": "bad",
        },
    )
    assert resp.status_code == 200


def test_rejects_obscured_report_against_unsafe_cluster(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "quality",
            "obscured": "true",
            "cluster_id": str(client.unsafe_cluster_id),
            "taste": "bad",
        },
    )
    assert resp.status_code == 400


def test_rejects_report_against_nonexistent_parcel(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": "999999",
            "event_subtype": "outage",
        },
    )
    assert resp.status_code == 400


def test_rejects_invalid_field_combination(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            # missing required event_subtype
        },
    )
    assert resp.status_code == 422


def test_rate_limit_blocks_after_threshold(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_DAY", "2")
    import rate_limit

    monkeypatch.setattr(rate_limit, "RATE_LIMIT_PER_DAY", 2)

    for _ in range(2):
        resp = client.post(
            "/api/reports",
            data={
                "report_type": "event",
                "obscured": "false",
                "parcel_id": str(client.parcel_id),
                "event_subtype": "outage",
            },
        )
        assert resp.status_code == 200

    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "outage",
        },
    )
    assert resp.status_code == 429
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_reports_api.py -v`
Expected: FAIL — `routers.reports` not defined / `/api/reports` returns 404

- [ ] **Step 4: Implement routers/reports.py**

`projects/mywater/routers/reports.py`:
```python
import uuid
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Request, Response, UploadFile

from db import get_db
from models import ReportCreate
from photos import PhotoValidationError, upload_photo
from rate_limit import hash_identifier, is_rate_limited, record_submission

router = APIRouter()

COOKIE_NAME = "mywater_id"


def _client_ip(request: Request):
    return request.headers.get(
        "cf-connecting-ip", request.client.host if request.client else "unknown"
    )


def _parcel_exists(conn, parcel_id):
    row = conn.execute("SELECT 1 FROM parcels_db.parcels WHERE id = ?", (parcel_id,)).fetchone()
    return row is not None


def _cluster_is_safe(conn, cluster_id):
    row = conn.execute(
        "SELECT anonymization_safe FROM parcels_db.parcel_clusters WHERE id = ?",
        (cluster_id,),
    ).fetchone()
    return row is not None and row[0] == 1


@router.post("/reports")
async def create_report(
    request: Request,
    response: Response,
    report_type: str = Form(...),
    obscured: bool = Form(...),
    parcel_id: Optional[int] = Form(None),
    cluster_id: Optional[int] = Form(None),
    free_text: Optional[str] = Form(None),
    taste: Optional[str] = Form(None),
    smell: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    pressure: Optional[str] = Form(None),
    event_subtype: Optional[str] = Form(None),
    ongoing: Optional[bool] = Form(None),
    photo: Optional[UploadFile] = File(None),
    mywater_id: Optional[str] = Cookie(None),
    conn=Depends(get_db),
):
    try:
        report = ReportCreate(
            report_type=report_type,
            obscured=obscured,
            parcel_id=parcel_id,
            cluster_id=cluster_id,
            free_text=free_text,
            taste=taste,
            smell=smell,
            color=color,
            pressure=pressure,
            event_subtype=event_subtype,
            ongoing=ongoing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if report.obscured:
        if not _cluster_is_safe(conn, report.cluster_id):
            raise HTTPException(
                status_code=400, detail="cluster_id is not a valid, anonymization-safe cluster"
            )
    else:
        if not _parcel_exists(conn, report.parcel_id):
            raise HTTPException(status_code=400, detail="parcel_id does not exist")

    cookie_id = mywater_id or str(uuid.uuid4())
    ip_hash = hash_identifier(_client_ip(request))
    cookie_hash = hash_identifier(cookie_id)

    if is_rate_limited(conn, ip_hash, cookie_hash):
        raise HTTPException(
            status_code=429, detail="you've reached today's report limit — try again tomorrow"
        )

    photo_url = None
    if photo is not None and photo.filename:
        content = await photo.read()
        try:
            photo_url = upload_photo(content, photo.content_type)
        except PhotoValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    cur = conn.execute(
        """
        INSERT INTO reports (
            report_type, obscured, parcel_id, cluster_id, free_text, photo_url,
            taste, smell, color, pressure, event_subtype, ongoing
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report.report_type,
            int(report.obscured),
            report.parcel_id,
            report.cluster_id,
            report.free_text,
            photo_url,
            report.taste,
            report.smell,
            report.color,
            report.pressure,
            report.event_subtype,
            int(report.ongoing) if report.ongoing is not None else None,
        ),
    )
    conn.commit()
    record_submission(conn, ip_hash, cookie_hash)

    response.set_cookie(
        COOKIE_NAME, cookie_id, max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax"
    )

    return {"id": cur.lastrowid, "report_type": report.report_type}
```

- [ ] **Step 5: Wire the router into main.py**

Edit `projects/mywater/main.py` — add after the `app = FastAPI(...)` line:
```python
from routers import reports  # noqa: E402

app.include_router(reports.router, prefix="/api")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_reports_api.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Run the full suite to confirm no regressions**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1-5)

- [ ] **Step 8: Commit**

```bash
git add projects/mywater/routers/reports.py projects/mywater/tests/conftest.py \
  projects/mywater/tests/test_reports_api.py projects/mywater/main.py
git commit -m "mywater: report submission endpoint"
```

---

### Task 6: GeoJSON serving endpoints

**Files:**
- Create: `projects/mywater/routers/parcels.py`
- Modify: `projects/mywater/routers/reports.py`
- Modify: `projects/mywater/main.py`
- Test: `projects/mywater/tests/test_parcels_api.py`
- Test: `projects/mywater/tests/test_reports_api.py` (append)

**Interfaces:**
- Consumes: `tests/conftest.py`'s `client` fixture (Task 5); `db.get_db` (Task 1).
- Produces: `routers.parcels.router` with `GET /api/parcels.geojson`, `GET /api/clusters.geojson`; `routers.reports.router` extended with `GET /api/reports.geojson` (optional `since`/`until` query params, ISO date strings). All return GeoJSON `FeatureCollection` dicts. This is the last task in this plan — the frontend plan consumes these three endpoints directly.

- [ ] **Step 1: Write the failing tests for parcels/clusters GeoJSON**

`projects/mywater/tests/test_parcels_api.py`:
```python
def test_parcels_geojson_returns_feature_collection_with_expected_properties(client):
    resp = client.get("/api/parcels.geojson")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    feature = next(f for f in body["features"] if f["properties"]["id"] == client.parcel_id)
    assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert feature["properties"]["apn"] == "TEST_APN_1"
    assert feature["properties"]["cluster_id"] is not None


def test_clusters_geojson_returns_feature_collection_with_anonymization_safe_flag(client):
    resp = client.get("/api/clusters.geojson")
    assert resp.status_code == 200
    body = resp.json()
    safe_feature = next(
        f for f in body["features"] if f["properties"]["id"] == client.safe_cluster_id
    )
    unsafe_feature = next(
        f for f in body["features"] if f["properties"]["id"] == client.unsafe_cluster_id
    )
    assert safe_feature["properties"]["anonymization_safe"] is True
    assert unsafe_feature["properties"]["anonymization_safe"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_parcels_api.py -v`
Expected: FAIL — `/api/parcels.geojson` returns 404

- [ ] **Step 3: Implement routers/parcels.py**

`projects/mywater/routers/parcels.py`:
```python
import json

from fastapi import APIRouter, Depends

from db import get_db

router = APIRouter()


@router.get("/parcels.geojson")
def parcels_geojson(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT id, apn, situsstr, cluster_id, centroid_lat, centroid_lng, AsGeoJSON(geometry) "
        "FROM parcels_db.parcels"
    ).fetchall()
    features = []
    for pid, apn, situsstr, cluster_id, lat, lng, geom_json in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(geom_json),
                "properties": {
                    "id": pid,
                    "apn": apn,
                    "situsstr": situsstr,
                    "cluster_id": cluster_id,
                    "centroid_lat": lat,
                    "centroid_lng": lng,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


@router.get("/clusters.geojson")
def clusters_geojson(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT id, street_name, centroid_lat, centroid_lng, parcel_count, anonymization_safe, "
        "AsGeoJSON(geometry) FROM parcels_db.parcel_clusters"
    ).fetchall()
    features = []
    for cid, street_name, lat, lng, parcel_count, safe, geom_json in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(geom_json),
                "properties": {
                    "id": cid,
                    "street_name": street_name,
                    "centroid_lat": lat,
                    "centroid_lng": lng,
                    "parcel_count": parcel_count,
                    "anonymization_safe": bool(safe),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
```

- [ ] **Step 4: Wire the parcels router into main.py**

Edit `projects/mywater/main.py` — add alongside the reports router import/include:
```python
from routers import parcels, reports  # noqa: E402

app.include_router(reports.router, prefix="/api")
app.include_router(parcels.router, prefix="/api")
```

(This replaces the single-router import/include line from Task 5 Step 5 with both routers.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_parcels_api.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Write the failing tests for reports GeoJSON, including the anonymization-leak test**

Append to `projects/mywater/tests/test_reports_api.py`:
```python
def test_reports_geojson_for_non_obscured_report_shows_parcel_centroid(client):
    client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "main_break",
        },
    )
    resp = client.get("/api/reports.geojson")
    assert resp.status_code == 200
    body = resp.json()
    feature = body["features"][0]
    assert feature["geometry"]["coordinates"] == [-122.6, 39.0]
    assert feature["properties"]["obscured"] is False


def test_reports_geojson_for_obscured_report_never_exposes_parcel_identity(client):
    client.post(
        "/api/reports",
        data={
            "report_type": "quality",
            "obscured": "true",
            "cluster_id": str(client.safe_cluster_id),
            "taste": "bad",
        },
    )
    resp = client.get("/api/reports.geojson")
    assert resp.status_code == 200
    body = resp.json()
    feature = body["features"][0]

    assert feature["properties"]["obscured"] is True
    assert "parcel_id" not in feature["properties"]
    assert "apn" not in feature["properties"]
    assert "cluster_id" not in feature["properties"]
    assert feature["properties"]["location_label"] == "area near MAIN ST"
    assert feature["geometry"]["coordinates"] == [-122.6, 39.0]


def test_reports_geojson_filters_by_since_and_until(client):
    client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "outage",
        },
    )
    far_future = "2999-01-01T00:00:00"
    resp = client.get("/api/reports.geojson", params={"since": far_future})
    assert resp.json()["features"] == []

    far_past = "2000-01-01T00:00:00"
    resp = client.get("/api/reports.geojson", params={"since": far_past})
    assert len(resp.json()["features"]) == 1
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_reports_api.py -v`
Expected: FAIL — `/api/reports.geojson` returns 404

- [ ] **Step 8: Implement GET /api/reports.geojson**

Append to `projects/mywater/routers/reports.py`:
```python
import json
from typing import Optional as _Optional  # noqa: F401 (Optional already imported above)


@router.get("/reports.geojson")
def reports_geojson(since: Optional[str] = None, until: Optional[str] = None, conn=Depends(get_db)):
    query = """
        SELECT
            r.id, r.report_type, r.obscured, r.created_at, r.free_text, r.photo_url,
            r.taste, r.smell, r.color, r.pressure, r.event_subtype, r.ongoing,
            CASE WHEN r.obscured = 1 THEN pc.centroid_lat ELSE p.centroid_lat END AS lat,
            CASE WHEN r.obscured = 1 THEN pc.centroid_lng ELSE p.centroid_lng END AS lng,
            CASE WHEN r.obscured = 1 THEN pc.street_name ELSE NULL END AS cluster_street_name
        FROM reports r
        LEFT JOIN parcels_db.parcels p ON r.obscured = 0 AND p.id = r.parcel_id
        LEFT JOIN parcels_db.parcel_clusters pc ON r.obscured = 1 AND pc.id = r.cluster_id
        WHERE 1 = 1
    """
    params = []
    if since:
        query += " AND r.created_at >= ?"
        params.append(since)
    if until:
        query += " AND r.created_at <= ?"
        params.append(until)
    query += " ORDER BY r.created_at DESC"

    rows = conn.execute(query, params).fetchall()
    features = []
    for row in rows:
        (
            rid, report_type, obscured, created_at, free_text, photo_url,
            taste, smell, color, pressure, event_subtype, ongoing,
            lat, lng, cluster_street_name,
        ) = row
        properties = {
            "id": rid,
            "report_type": report_type,
            "obscured": bool(obscured),
            "created_at": created_at,
            "free_text": free_text,
            "photo_url": photo_url,
            "taste": taste,
            "smell": smell,
            "color": color,
            "pressure": pressure,
            "event_subtype": event_subtype,
            "ongoing": bool(ongoing) if ongoing is not None else None,
        }
        if obscured:
            properties["location_label"] = (
                f"area near {cluster_street_name}" if cluster_street_name else "area near unknown street"
            )
        geometry = None
        if lat is not None and lng is not None:
            geometry = {"type": "Point", "coordinates": [lng, lat]}
        features.append({"type": "Feature", "geometry": geometry, "properties": properties})
    return {"type": "FeatureCollection", "features": features}
```

Note: the `import json` and unused `_Optional` alias at the top of this appended block are only needed if `json`/`Optional` aren't already imported at the top of `routers/reports.py` from Task 5. Since Task 5's version already has `from typing import Optional`, only add `import json` — drop the `_Optional` alias line, it was a placeholder to flag this check, not real code to keep.

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/test_reports_api.py -v`
Expected: PASS (9 tests: 6 from Task 5 + 3 new)

- [ ] **Step 10: Run the full suite to confirm no regressions**

Run: `cd projects/mywater && conda activate mywater && python -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1-6, no warnings)

- [ ] **Step 11: Commit**

```bash
git add projects/mywater/routers/parcels.py projects/mywater/routers/reports.py \
  projects/mywater/main.py projects/mywater/tests/test_parcels_api.py \
  projects/mywater/tests/test_reports_api.py
git commit -m "mywater: GeoJSON serving endpoints for parcels, clusters, and reports"
```

---

## Self-Review Notes

- **Spec coverage**: Report Submission Flow & Abuse Mitigation (rate limiting, photo constraints, immediate publish, no accounts) — Tasks 3, 4, 5. Data Model's `reports`/`submission_log` tables and the parcel_id/cluster_id mutual-exclusivity invariant — Tasks 1, 2, 5 (enforced at both the Pydantic layer and a DB-level `CHECK` constraint, belt-and-suspenders). Anonymization guarantee (obscured reports never expose parcel identity, only safe clusters) — Task 5 (validates `anonymization_safe` before accepting) and Task 6 (the `reports.geojson` query structurally excludes parcel-level joins for obscured rows, and a test directly asserts no `parcel_id`/`apn`/`cluster_id` leak). Two-file DB split — Task 1's `db.py` design. Map/Timeline UI's data needs (parcels, clusters, date-filtered reports as GeoJSON) — Task 6. HTML/HTMX/templates, the map/timeline UI itself, and the About/FAQ page are explicitly out of scope for this plan (frontend plan).
- **Placeholder scan**: found one — Task 6 Step 8 originally included a placeholder-flagging comment about an unused `_Optional` import; corrected inline to clarify only `import json` is actually needed, with the placeholder line explicitly called out as not-real-code rather than left ambiguous.
- **Type consistency**: `ReportCreate` (Task 2) field names and types match exactly what Task 5's endpoint constructs it from (`Form(...)` parameter names line up 1:1 with `ReportCreate` field names). `get_db`/`get_connection` (Task 1) signatures match what Task 5's `conftest.py` override and Task 6's endpoints both depend on via `Depends(get_db)`. The `anonymization_safe` column and `MIN_CLUSTER_SIZE` semantics match precompute's existing schema exactly (verified against the merged `precompute/schema.sql` and `precompute/cluster.py`, not assumed).
- **Decisions made during planning, not fully specified in the spec** (flagged for the user, not hidden): quality-report field requirements (at least one rating or free_text) and event-report field requirements (event_subtype required, no quality fields) were decided here, not dictated by the spec — see Global Constraints. The two-file DB split is a spec revision made during this planning session (see the spec's Architecture & Stack section, updated 2026-08-18) after discovering precompute's rebuild would otherwise delete all report data.
