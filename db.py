from pathlib import Path

from precompute.load import connect as _connect_spatialite

APP_SCHEMA_PATH = Path(__file__).parent / "db_app_schema.sql"
DEFAULT_APP_DB_PATH = Path(__file__).parent / "mywater_app.db"
DEFAULT_PARCELS_DB_PATH = Path(__file__).parent / "mywater.db"


def init_app_db(app_db_path=None):
    if app_db_path is None:
        app_db_path = DEFAULT_APP_DB_PATH
    conn = _connect_spatialite(str(app_db_path))
    try:
        with open(APP_SCHEMA_PATH) as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()


def get_connection(app_db_path=None, parcels_db_path=None):
    if app_db_path is None:
        app_db_path = DEFAULT_APP_DB_PATH
    if parcels_db_path is None:
        parcels_db_path = DEFAULT_PARCELS_DB_PATH
    # SQLite's ATTACH DATABASE silently CREATES an empty file when the path
    # doesn't exist, rather than erroring — so without this check, a missing
    # mywater.db (e.g. fresh deploy before precompute has run, or a
    # misconfigured path) would produce a 0-byte attached database and every
    # subsequent query would fail with a confusing "no such table" instead
    # of a clear signal about what's actually wrong.
    if not Path(parcels_db_path).exists():
        raise RuntimeError(
            f"Parcels database not found at {parcels_db_path} — "
            "has the precompute pipeline been run?"
        )
    conn = _connect_spatialite(str(app_db_path))
    try:
        conn.execute("ATTACH DATABASE ? AS parcels_db", (str(parcels_db_path),))
    except Exception:
        conn.close()
        raise
    return conn


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
