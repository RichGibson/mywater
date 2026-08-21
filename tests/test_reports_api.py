import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

from precompute.load import connect as spatialite_connect
from tests.conftest import _square

# Allowlist for an obscured report's GeoJSON properties. Asserting against
# this (rather than checking a handful of forbidden keys) means the test
# fails on ANY unexpected key showing up, not just the ones we thought to
# check for.
ALLOWED_OBSCURED_KEYS = {
    "id", "report_type", "obscured", "created_at", "free_text", "photo_url",
    "taste", "smell", "color", "pressure", "event_subtype", "ongoing", "location_label",
}


def test_create_non_obscured_event_report_succeeds(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "main_break",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_type"] == "event"
    assert "mywater_id" in resp.cookies


def test_create_obscured_quality_report_succeeds(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "quality",
            "obscured": "true",
            "cluster_id": str(client.safe_cluster_id),
            "taste": "bad",
        },
    )
    assert resp.status_code == 200


def test_rejects_obscured_report_against_unsafe_cluster(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "quality",
            "obscured": "true",
            "cluster_id": str(client.unsafe_cluster_id),
            "taste": "bad",
        },
    )
    assert resp.status_code == 400


def test_rejects_report_against_nonexistent_parcel(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": "999999",
            "event_subtype": "outage",
        },
    )
    assert resp.status_code == 400


def test_rejects_invalid_field_combination(client):
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            # missing required event_subtype
        },
    )
    assert resp.status_code == 422


def test_rate_limit_blocks_after_threshold(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_DAY", "2")
    import rate_limit

    monkeypatch.setattr(rate_limit, "RATE_LIMIT_PER_DAY", 2)

    for _ in range(2):
        resp = client.post(
            "/api/reports",
            data={
                "report_type": "event",
                "obscured": "false",
                "parcel_id": str(client.parcel_id),
                "event_subtype": "outage",
            },
        )
        assert resp.status_code == 200

    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "outage",
        },
    )
    assert resp.status_code == 429


def test_reports_geojson_for_non_obscured_report_shows_parcel_centroid(client):
    client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "main_break",
        },
    )
    resp = client.get("/api/reports.geojson")
    assert resp.status_code == 200
    body = resp.json()
    feature = body["features"][0]
    assert feature["geometry"]["coordinates"] == [-122.6, 39.0]
    assert feature["properties"]["obscured"] is False


def test_reports_geojson_for_obscured_report_never_exposes_parcel_identity(client):
    client.post(
        "/api/reports",
        data={
            "report_type": "quality",
            "obscured": "true",
            "cluster_id": str(client.safe_cluster_id),
            "taste": "bad",
        },
    )
    resp = client.get("/api/reports.geojson")
    assert resp.status_code == 200
    body = resp.json()
    feature = body["features"][0]

    assert feature["properties"]["obscured"] is True
    assert set(feature["properties"]) <= ALLOWED_OBSCURED_KEYS
    assert feature["properties"]["location_label"] == "area near MAIN ST"
    # The safe cluster's centroid (39.5, -122.9) is deliberately different
    # from the parcel's centroid (39.0, -122.6) in tests/conftest.py, so this
    # assertion would fail if the join leaked parcel-level coordinates.
    assert feature["geometry"]["coordinates"] == [-122.9, 39.5]
    assert feature["geometry"]["coordinates"] != [-122.6, 39.0]


def test_reports_geojson_suppresses_photo_url_for_obscured_report(client):
    # An obscured report's photo may still carry GPS EXIF data server-side
    # (EXIF stripping is out of scope here), so the API must never publish
    # its URL — otherwise the "obscured" guarantee is defeated by anyone who
    # fetches the photo and reads its metadata.
    with patch(
        "routers.reports.upload_photo",
        return_value="https://photos.example.com/should-not-appear.jpg",
    ):
        resp = client.post(
            "/api/reports",
            data={
                "report_type": "quality",
                "obscured": "true",
                "cluster_id": str(client.safe_cluster_id),
                "taste": "bad",
            },
            files={"photo": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
        )
    assert resp.status_code == 200

    resp = client.get("/api/reports.geojson")
    body = resp.json()
    feature = body["features"][0]
    assert feature["properties"]["obscured"] is True
    assert feature["properties"]["photo_url"] is None


def test_reports_geojson_shows_photo_url_for_non_obscured_report(client):
    # Non-obscured reports already reveal exact location via parcel_id, so a
    # photo's EXIF data doesn't add new exposure there — confirms Critical
    # #1's fix suppresses photo_url only for obscured reports, not globally.
    with patch(
        "routers.reports.upload_photo",
        return_value="https://photos.example.com/parcel-photo.jpg",
    ):
        resp = client.post(
            "/api/reports",
            data={
                "report_type": "event",
                "obscured": "false",
                "parcel_id": str(client.parcel_id),
                "event_subtype": "main_break",
            },
            files={"photo": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
        )
    assert resp.status_code == 200

    resp = client.get("/api/reports.geojson")
    body = resp.json()
    feature = body["features"][0]
    assert feature["properties"]["obscured"] is False
    assert feature["properties"]["photo_url"] == "https://photos.example.com/parcel-photo.jpg"


def test_reports_geojson_fails_closed_when_cluster_becomes_unsafe_after_submission(
    client, parcels_db_path
):
    # cluster_id is not stable across precompute rebuilds: a report's stored
    # cluster_id could end up pointing at a different, unsafe cluster after a
    # rebuild. The read path must re-check anonymization_safe at query time
    # and fail closed (no geometry) rather than keep serving a now-unsafe
    # cluster's exact coordinates under an "obscured: true" label.
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "quality",
            "obscured": "true",
            "cluster_id": str(client.safe_cluster_id),
            "taste": "bad",
        },
    )
    assert resp.status_code == 200

    parcels_path, _parcel_id, safe_cluster_id, _unsafe_cluster_id = parcels_db_path
    raw_conn = sqlite3.connect(str(parcels_path))
    raw_conn.execute(
        "UPDATE parcel_clusters SET anonymization_safe = 0 WHERE id = ?", (safe_cluster_id,)
    )
    raw_conn.commit()
    raw_conn.close()

    resp = client.get("/api/reports.geojson")
    assert resp.status_code == 200
    body = resp.json()
    feature = body["features"][0]
    assert feature["properties"]["obscured"] is True
    assert feature["geometry"] is None


def test_report_stores_parcel_apn_at_write_time(client, app_db_path):
    # Fix 1 regression test (part 1): the write path must persist the
    # parcel's stable apn alongside the unstable parcel_id, so a later
    # precompute rebuild that renumbers parcel_id can't misattribute this
    # report to a different physical parcel.
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "main_break",
        },
    )
    assert resp.status_code == 200
    report_id = resp.json()["id"]

    raw_conn = sqlite3.connect(str(app_db_path))
    row = raw_conn.execute(
        "SELECT parcel_id, parcel_apn FROM reports WHERE id = ?", (report_id,)
    ).fetchone()
    raw_conn.close()
    assert row == (client.parcel_id, "TEST_APN_1")


def test_reports_geojson_resolves_by_apn_not_by_stale_parcel_id(client, parcels_db_path):
    # Fix 1 regression test (part 2): simulates a precompute rebuild that
    # renumbers parcel_id for the same physical parcel (same apn, new id).
    # If the geojson read path still joined on parcel_id (the pre-fix
    # behavior), this report's geometry would silently disappear (old id no
    # longer exists) or, worse in a real rebuild, resolve to a DIFFERENT
    # physical parcel that happened to get the same id. Joining on apn must
    # keep resolving to the correct, current row for the same physical
    # parcel regardless of what id it was assigned this time around.
    resp = client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "main_break",
        },
    )
    assert resp.status_code == 200

    parcels_path, old_parcel_id, safe_cluster_id, _unsafe_cluster_id = parcels_db_path

    # Simulate a precompute rebuild: the same physical parcel (same apn)
    # comes back from the county ArcGIS fetch in a different order and is
    # assigned a brand-new id, with an updated centroid (e.g. a corrected
    # survey). We delete-and-reinsert rather than UPDATE because `id` is an
    # AUTOINCREMENT PRIMARY KEY.
    raw_conn = spatialite_connect(str(parcels_path))
    raw_conn.execute("DELETE FROM parcels WHERE id = ?", (old_parcel_id,))
    new_square = _square(3, 3).wkt
    raw_conn.execute(
        "INSERT INTO parcels "
        "(id, apn, situsstr, situsnum, cluster_id, centroid_lat, centroid_lng, geometry) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ST_GeomFromText(?, 4326))",
        (
            old_parcel_id + 500,
            "TEST_APN_1",  # same apn — same physical parcel
            "MAIN ST",
            "100",
            safe_cluster_id,
            39.7,  # deliberately different centroid than the original (39.0, -122.6)
            -122.77,
            new_square,
        ),
    )
    raw_conn.commit()
    raw_conn.close()

    resp = client.get("/api/reports.geojson")
    assert resp.status_code == 200
    body = resp.json()
    feature = body["features"][0]
    assert feature["properties"]["obscured"] is False
    # Resolved via apn to the post-"rebuild" row's new centroid, not left
    # null (which is what joining on the now-deleted old id would produce)
    # and not stuck on the pre-rebuild centroid.
    assert feature["geometry"] is not None
    assert feature["geometry"]["coordinates"] == [-122.77, 39.7]


def test_reports_geojson_filters_by_since_and_until(client):
    client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "outage",
        },
    )
    far_future = "2999-01-01T00:00:00"
    resp = client.get("/api/reports.geojson", params={"since": far_future})
    assert resp.json()["features"] == []

    far_past = "2000-01-01T00:00:00"
    resp = client.get("/api/reports.geojson", params={"since": far_past})
    assert len(resp.json()["features"]) == 1

    # until alone (previously untested despite the test name implying it was)
    resp = client.get("/api/reports.geojson", params={"until": far_past})
    assert resp.json()["features"] == []

    resp = client.get("/api/reports.geojson", params={"until": far_future})
    assert len(resp.json()["features"]) == 1


def test_reports_geojson_date_only_until_includes_whole_day(client):
    client.post(
        "/api/reports",
        data={
            "report_type": "event",
            "obscured": "false",
            "parcel_id": str(client.parcel_id),
            "event_subtype": "outage",
        },
    )
    # created_at is generated server-side via SQLite's strftime('...', 'now'),
    # which is UTC, matching datetime.now(timezone.utc) here.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    resp = client.get("/api/reports.geojson", params={"until": today})
    assert resp.status_code == 200
    assert len(resp.json()["features"]) == 1


def test_reports_geojson_rejects_malformed_date_params(client):
    resp = client.get("/api/reports.geojson", params={"since": "not-a-date"})
    assert resp.status_code == 422

    resp = client.get("/api/reports.geojson", params={"until": "also-not-a-date"})
    assert resp.status_code == 422
