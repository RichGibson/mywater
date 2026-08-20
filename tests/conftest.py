from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import MultiPolygon, Polygon

from db import get_db, init_app_db
from precompute.load import connect as spatialite_connect
from precompute.load import init_schema as init_parcels_schema

PARCELS_SCHEMA_PATH = Path(__file__).parent.parent / "precompute" / "schema.sql"


def _square(cx, cy, size=0.001):
    # Returned as a MultiPolygon (not a bare Polygon) because the parcels
    # schema constrains the `geometry` columns to MULTIPOLYGON via
    # AddGeometryColumn; a bare Polygon's WKT fails that constraint.
    return MultiPolygon(
        [
            Polygon(
                [
                    (cx - size / 2, cy - size / 2),
                    (cx + size / 2, cy - size / 2),
                    (cx + size / 2, cy + size / 2),
                    (cx - size / 2, cy + size / 2),
                ]
            )
        ]
    )


@pytest.fixture(autouse=True)
def rate_limit_pepper(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PEPPER", "test-pepper-value")


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
        # Centroid is deliberately different from the parcel's centroid below
        # (39.0, -122.6) so tests can distinguish "coordinates came from the
        # cluster" from "coordinates came from the parcel" — see
        # test_reports_geojson_for_obscured_report_never_exposes_parcel_identity.
        ("MAIN ST", 39.5, -122.9, 8, 1, _square(0, 0).wkt),
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
