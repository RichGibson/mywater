SELECT InitSpatialMetaData(1);

CREATE TABLE parcel_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    street_name TEXT NOT NULL,
    centroid_lat REAL NOT NULL,
    centroid_lng REAL NOT NULL,
    parcel_count INTEGER NOT NULL,
    anonymization_safe INTEGER NOT NULL DEFAULT 1
);
SELECT AddGeometryColumn('parcel_clusters', 'geometry', 4326, 'MULTIPOLYGON', 'XY');
SELECT CreateSpatialIndex('parcel_clusters', 'geometry');

CREATE TABLE parcels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apn TEXT NOT NULL UNIQUE,
    situsstr TEXT,
    situsnum TEXT,
    cluster_id INTEGER NOT NULL REFERENCES parcel_clusters(id),
    centroid_lat REAL NOT NULL,
    centroid_lng REAL NOT NULL
);
SELECT AddGeometryColumn('parcels', 'geometry', 4326, 'MULTIPOLYGON', 'XY');
SELECT CreateSpatialIndex('parcels', 'geometry');
