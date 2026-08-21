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


def test_get_connection_raises_clear_error_when_parcels_db_missing(tmp_path):
    # Fix 4: SQLite's ATTACH DATABASE silently creates an empty file for a
    # nonexistent path instead of erroring, which previously turned a
    # missing/misconfigured mywater.db into confusing downstream
    # "OperationalError: no such table" failures on every real query. This
    # must fail loudly and clearly at connection time instead.
    from db import get_connection, init_app_db

    app_db_path = tmp_path / "mywater_app.db"
    init_app_db(app_db_path)

    missing_parcels_db_path = tmp_path / "does_not_exist.db"
    assert not missing_parcels_db_path.exists()

    with pytest.raises(RuntimeError, match="does_not_exist.db"):
        get_connection(app_db_path=app_db_path, parcels_db_path=missing_parcels_db_path)

    # Confirm ATTACH's silent-file-creation behavior didn't sneak through.
    assert not missing_parcels_db_path.exists()


def test_health_check_returns_ok(tmp_path, monkeypatch):
    import db
    from fastapi.testclient import TestClient

    monkeypatch.setattr(db, "DEFAULT_APP_DB_PATH", tmp_path / "mywater_app.db")
    from main import app

    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
