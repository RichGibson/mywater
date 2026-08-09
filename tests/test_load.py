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
