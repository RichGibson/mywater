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
