"""Insert synthetic reports into mywater_app.db for local testing.

Generates 100 reports:
  - 90 on random parcels/clusters, spread over the last year
  - 5 of those 90 backdated to more than a year ago
  - 5 additional reports on parcels reused from the 90 above
  - 5 additional reports on clusters reused from the 90 above

Only clusters with anonymization_safe = 1 are used, matching the real
obscured-reporting path in routers/reports.py. Existing rows in
mywater_app.db are left alone; this only adds new reports.

Requires the mywater conda environment (SpatiaLite support) and an
already-built mywater.db (see README: python -m precompute.run).

Usage:
    python scripts/generate_sample_reports.py [--seed N]
"""
import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import get_connection, init_app_db  # noqa: E402

TOTAL_REPORTS = 100
PARCEL_REPEAT_COUNT = 5
CLUSTER_REPEAT_COUNT = 5
OLD_REPORT_COUNT = 5
RANDOM_REPORT_COUNT = TOTAL_REPORTS - PARCEL_REPEAT_COUNT - CLUSTER_REPEAT_COUNT

OBSCURED_PROBABILITY = 0.4
EVENT_PROBABILITY = 0.35

QUALITY_RATINGS = ["good", "off", "bad"]
QUALITY_RATING_WEIGHTS = [0.6, 0.3, 0.1]

EVENT_SUBTYPES = ["main_break", "outage", "boil_notice", "other"]

QUALITY_FREE_TEXT = [
    "Water tasted metallic today, worse than usual.",
    "Noticed a chlorine smell after the county flushed the lines.",
    "Water came out brown for about ten minutes this morning.",
    "Pressure has been low since Tuesday.",
    "Smells like rotten eggs when the tap runs hot.",
    "Slight cloudiness in the water, cleared up after a minute.",
    "Water looked fine but had an odd aftertaste.",
    "Pressure drops every evening around dinner time.",
    None,
    None,
]

EVENT_FREE_TEXT = {
    "main_break": [
        "Water main broke near the intersection, crew is on site.",
        "Saw water bubbling up through the pavement this morning.",
        "Main break flooded the ditch along the road.",
    ],
    "outage": [
        "No water pressure at all since this morning.",
        "Water has been out for a few hours, no notice from the county yet.",
        "Outage started overnight, still out as of this report.",
    ],
    "boil_notice": [
        "County issued a boil water notice for this area.",
        "Got a boil notice flyer on the door today.",
    ],
    "other": [
        "Truck hit a fire hydrant down the block, water everywhere.",
        "Contractor cut a line while digging, water shut off for repairs.",
        None,
    ],
}

INSERT_SQL = """
    INSERT INTO reports (
        report_type, obscured, parcel_id, parcel_apn, cluster_id, created_at,
        free_text, photo_url, taste, smell, color, pressure, event_subtype, ongoing
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def random_recent_datetime(now):
    return now - timedelta(days=random.uniform(0, 365))


def random_old_datetime(now):
    return now - timedelta(days=random.uniform(366, 730))


def format_timestamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def make_quality_fields():
    fields = {"taste": None, "smell": None, "color": None, "pressure": None}
    for field in random.sample(list(fields), k=random.randint(1, 4)):
        fields[field] = random.choices(QUALITY_RATINGS, weights=QUALITY_RATING_WEIGHTS)[0]
    return fields, random.choice(QUALITY_FREE_TEXT)


def make_event_fields():
    event_subtype = random.choice(EVENT_SUBTYPES)
    ongoing = random.choice([True, False])
    free_text = random.choice(EVENT_FREE_TEXT[event_subtype])
    return event_subtype, ongoing, free_text


def build_report(location, now, old=False):
    """location is ("parcel", id, apn) or ("cluster", id, street_name)."""
    loc_type, loc_id, apn_or_street = location
    obscured = loc_type == "cluster"
    is_event = random.random() < EVENT_PROBABILITY
    created_at = random_old_datetime(now) if old else random_recent_datetime(now)

    row = {
        "report_type": "event" if is_event else "quality",
        "obscured": 1 if obscured else 0,
        "parcel_id": None if obscured else loc_id,
        "parcel_apn": None if obscured else apn_or_street,
        "cluster_id": loc_id if obscured else None,
        "created_at": format_timestamp(created_at),
        "free_text": None,
        "photo_url": None,
        "taste": None,
        "smell": None,
        "color": None,
        "pressure": None,
        "event_subtype": None,
        "ongoing": None,
    }

    if is_event:
        event_subtype, ongoing, free_text = make_event_fields()
        row["event_subtype"] = event_subtype
        row["ongoing"] = 1 if ongoing else 0
        row["free_text"] = free_text
    else:
        fields, free_text = make_quality_fields()
        row.update(fields)
        row["free_text"] = free_text

    return row


def insert_report(conn, row):
    conn.execute(
        INSERT_SQL,
        (
            row["report_type"], row["obscured"], row["parcel_id"], row["parcel_apn"],
            row["cluster_id"], row["created_at"], row["free_text"], row["photo_url"],
            row["taste"], row["smell"], row["color"], row["pressure"],
            row["event_subtype"], row["ongoing"],
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible output")
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    init_app_db()
    conn = get_connection()
    try:
        parcels = conn.execute("SELECT id, apn FROM parcels_db.parcels").fetchall()
        clusters = conn.execute(
            "SELECT id, street_name FROM parcels_db.parcel_clusters WHERE anonymization_safe = 1"
        ).fetchall()
        if not parcels or not clusters:
            raise RuntimeError("mywater.db has no parcels or no safe clusters, run precompute first")

        parcel_by_id = dict(parcels)
        cluster_by_id = dict(clusters)
        now = datetime.now(timezone.utc)
        old_indices = set(random.sample(range(RANDOM_REPORT_COUNT), OLD_REPORT_COUNT))

        used_parcels = []
        used_clusters = []
        rows = []

        for i in range(RANDOM_REPORT_COUNT):
            if random.random() < OBSCURED_PROBABILITY:
                cluster_id, street_name = random.choice(clusters)
                location = ("cluster", cluster_id, street_name)
                used_clusters.append(cluster_id)
            else:
                parcel_id, apn = random.choice(parcels)
                location = ("parcel", parcel_id, apn)
                used_parcels.append(parcel_id)
            rows.append(build_report(location, now, old=i in old_indices))

        for _ in range(PARCEL_REPEAT_COUNT):
            parcel_id = random.choice(used_parcels) if used_parcels else random.choice(parcels)[0]
            rows.append(build_report(("parcel", parcel_id, parcel_by_id[parcel_id]), now))

        for _ in range(CLUSTER_REPEAT_COUNT):
            cluster_id = random.choice(used_clusters) if used_clusters else random.choice(clusters)[0]
            rows.append(build_report(("cluster", cluster_id, cluster_by_id[cluster_id]), now))

        for row in rows:
            insert_report(conn, row)
        conn.commit()

        exact_count = sum(1 for r in rows if not r["obscured"])
        event_count = sum(1 for r in rows if r["report_type"] == "event")
        print(f"Inserted {len(rows)} reports into mywater_app.db")
        print(f"  exact: {exact_count}, obscured: {len(rows) - exact_count}")
        print(f"  event: {event_count}, quality: {len(rows) - event_count}")
        print(f"  older than 1 year: {OLD_REPORT_COUNT}")
        print(f"  parcel-repeat reports: {PARCEL_REPEAT_COUNT}, cluster-repeat reports: {CLUSTER_REPEAT_COUNT}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
