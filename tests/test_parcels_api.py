def test_parcels_geojson_returns_feature_collection_with_expected_properties(client):
    resp = client.get("/api/parcels.geojson")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    feature = next(f for f in body["features"] if f["properties"]["id"] == client.parcel_id)
    assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert feature["properties"]["apn"] == "TEST_APN_1"
    assert feature["properties"]["cluster_id"] is not None


def test_clusters_geojson_returns_feature_collection_with_anonymization_safe_flag(client):
    resp = client.get("/api/clusters.geojson")
    assert resp.status_code == 200
    body = resp.json()
    safe_feature = next(
        f for f in body["features"] if f["properties"]["id"] == client.safe_cluster_id
    )
    unsafe_feature = next(
        f for f in body["features"] if f["properties"]["id"] == client.unsafe_cluster_id
    )
    assert safe_feature["properties"]["anonymization_safe"] is True
    assert unsafe_feature["properties"]["anonymization_safe"] is False
