import sqlite3

_EXTENSION_CANDIDATES = [
    "mod_spatialite",
    "mod_spatialite.dylib",
    "mod_spatialite.so",
    "/opt/homebrew/lib/mod_spatialite.dylib",
    "/opt/anaconda3/envs/mywater/lib/mod_spatialite.dylib",
    "/usr/local/lib/mod_spatialite.8.dylib",
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
