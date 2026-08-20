import sqlite3

from shapely.geometry import MultiPolygon

from precompute.cluster import MIN_CLUSTER_SIZE

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
    # check_same_thread=False: FastAPI dispatches sync dependency generators
    # (e.g. db.get_db) through a worker thread separate from the thread that
    # runs the (async) route handler body, so a single request's connection
    # legitimately crosses threads. The connection is still only ever used
    # sequentially within one request/one caller, never concurrently from
    # multiple threads at once, so this is safe.
    conn = sqlite3.connect(db_path, check_same_thread=False)
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


def _to_multipolygon_wkt(geom):
    if geom.geom_type == "Polygon":
        geom = MultiPolygon([geom])
    return geom.wkt


def load_clusters_and_parcels(conn, clusters):
    with conn:
        cur = conn.cursor()
        for cluster in clusters:
            anonymization_safe = 1 if cluster["parcel_count"] >= MIN_CLUSTER_SIZE else 0
            cur.execute(
                """
                INSERT INTO parcel_clusters
                    (street_name, centroid_lat, centroid_lng, parcel_count, anonymization_safe, geometry)
                VALUES (?, ?, ?, ?, ?, ST_GeomFromText(?, 4326))
                """,
                (
                    cluster["street_name"],
                    cluster["centroid_lat"],
                    cluster["centroid_lng"],
                    cluster["parcel_count"],
                    anonymization_safe,
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
