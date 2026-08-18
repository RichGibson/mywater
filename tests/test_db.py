from pathlib import Path


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


def test_health_check_returns_ok(tmp_path, monkeypatch):
    import db
    from fastapi.testclient import TestClient

    monkeypatch.setattr(db, "DEFAULT_APP_DB_PATH", tmp_path / "mywater_app.db")
    from main import app

    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
