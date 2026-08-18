from pathlib import Path

import pytest
from shapely.geometry import Polygon

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
        },
        {
            "street_name": "OAK LN",
            "geometry": _square(20, 0),
            "centroid_lat": 0.0,
            "centroid_lng": 20.0,
            "parcel_count": 8,
            "members": [
                {"apn": f"C{i}", "situsstr": "OAK LN", "situsnum": str(100 + i), "geometry": _square(20 + i, 0)}
                for i in range(8)
            ],
        },
    ]
    load_clusters_and_parcels(conn, clusters)

    cluster_rows = conn.execute(
        "SELECT id, street_name, parcel_count, anonymization_safe FROM parcel_clusters ORDER BY id"
    ).fetchall()
    # MAIN ST has 2 parcels (< MIN_CLUSTER_SIZE, unsafe); OAK LN has 8 (safe).
    assert cluster_rows == [(1, "MAIN ST", 2, 0), (2, "OAK LN", 8, 1)]

    parcel_rows = conn.execute(
        "SELECT apn, cluster_id FROM parcels WHERE apn IN ('A', 'B') ORDER BY apn"
    ).fetchall()
    assert parcel_rows == [("A", 1), ("B", 1)]

    # Verify geometry types
    cluster_geom_type = conn.execute(
        "SELECT GeometryType(geometry) FROM parcel_clusters WHERE id = 1"
    ).fetchone()[0]
    assert cluster_geom_type == "MULTIPOLYGON"

    parcel_a_geom_type = conn.execute(
        "SELECT GeometryType(geometry) FROM parcels WHERE apn = 'A'"
    ).fetchone()[0]
    assert parcel_a_geom_type == "MULTIPOLYGON"

    parcel_b_geom_type = conn.execute(
        "SELECT GeometryType(geometry) FROM parcels WHERE apn = 'B'"
    ).fetchone()[0]
    assert parcel_b_geom_type == "MULTIPOLYGON"

    # Verify centroid values
    parcel_a_lat, parcel_a_lng = conn.execute(
        "SELECT centroid_lat, centroid_lng FROM parcels WHERE apn = 'A'"
    ).fetchone()
    assert parcel_a_lat == pytest.approx(0.0, abs=0.01)
    assert parcel_a_lng == pytest.approx(1.0, abs=0.01)

    parcel_b_lat, parcel_b_lng = conn.execute(
        "SELECT centroid_lat, centroid_lng FROM parcels WHERE apn = 'B'"
    ).fetchone()
    assert parcel_b_lat == pytest.approx(0.0, abs=0.01)
    assert parcel_b_lng == pytest.approx(3.0, abs=0.01)
