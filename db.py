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
