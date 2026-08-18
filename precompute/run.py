import argparse
from pathlib import Path

from precompute.cluster import MAX_CLUSTER_SIZE, MIN_CLUSTER_SIZE, cluster_parcels_by_street
from precompute.fetch import fetch_parcels, fetch_roadways
from precompute.load import connect, init_schema, load_clusters_and_parcels

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path(__file__).parent.parent / "mywater.db"
COMMUNITY_NAME = "CLEARLAKE OAKS"


def main(db_path=DEFAULT_DB_PATH):
    print(f"Fetching parcels for community '{COMMUNITY_NAME}'...")
    parcels, repaired_apns = fetch_parcels(COMMUNITY_NAME)
    print(f"Fetched {len(parcels)} parcels.")

    if repaired_apns:
        print(f"WARNING: repaired {len(repaired_apns)} parcels with invalid geometry: {repaired_apns}")

    print("Fetching roadway centerlines...")
    roadways = fetch_roadways()
    print(f"Fetched {len(roadways)} roadway segments.")

    clusters, excluded, outlier_indices = cluster_parcels_by_street(parcels, roadways)
    print(f"Built {len(clusters)} clusters from {len(parcels) - len(excluded)} parcels.")

    if excluded:
        print(f"WARNING: excluded {len(excluded)} parcels with no geometry or street name: {excluded}")

    if outlier_indices:
        print(
            f"WARNING: {len(outlier_indices)} clusters outside the "
            f"{MIN_CLUSTER_SIZE}-{MAX_CLUSTER_SIZE} parcel target range, flagged for manual review:"
        )
        for i in outlier_indices:
            c = clusters[i]
            print(f"  - {c['street_name']}: {c['parcel_count']} parcels")

    unsafe_clusters = [c for c in clusters if c["parcel_count"] < MIN_CLUSTER_SIZE]
    if unsafe_clusters:
        unsafe_pct = 100 * len(unsafe_clusters) / len(clusters) if clusters else 0
        print(
            f"WARNING: {len(unsafe_clusters)} clusters ({unsafe_pct:.1f}%) are below the "
            f"{MIN_CLUSTER_SIZE}-parcel anonymization minimum and are NOT safe to offer as "
            f"obscured-location targets"
        )

    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    conn = connect(str(db_path))
    init_schema(conn, SCHEMA_PATH)
    load_clusters_and_parcels(conn, clusters)
    conn.close()
    print(
        f"Wrote {len(clusters)} clusters and "
        f"{sum(c['parcel_count'] for c in clusters)} parcels to {db_path}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the mywater parcel/cluster database.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    main(db_path=args.db_path)
