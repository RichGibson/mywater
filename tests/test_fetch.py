from unittest.mock import MagicMock, patch

import pytest


def _geojson_response(features, error=None, exceeded_transfer_limit=None):
    mock_resp = MagicMock()
    if error is not None:
        mock_resp.json.return_value = {"error": error}
    else:
        response = {"type": "FeatureCollection", "features": features}
        if exceeded_transfer_limit is not None:
            response["exceededTransferLimit"] = exceeded_transfer_limit
        mock_resp.json.return_value = response
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def _feature(apn, situsstr, situsnum, situsfull, coords):
    return {
        "type": "Feature",
        "properties": {
            "APN": apn,
            "SITUSSTR": situsstr,
            "SITUSNUM": situsnum,
            "SITUSFULL": situsfull,
        },
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


def test_fetch_parcels_parses_single_page():
    from precompute.fetch import fetch_parcels

    coords = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    page = [_feature("APN1", "MAIN ST", "100", "CLEARLAKE OAKS", coords)]
    with patch("precompute.fetch.requests.get", return_value=_geojson_response(page)) as mock_get:
        result, repaired_apns = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 1
    assert result[0]["apn"] == "APN1"
    assert result[0]["situsstr"] == "MAIN ST"
    assert result[0]["geometry"] is not None
    assert repaired_apns == []
    mock_get.assert_called_once()
    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["where"] == "SITUSFULL LIKE '%CLEARLAKE OAKS%'"
    assert called_params["outSR"] == 4326


def test_fetch_parcels_paginates_full_pages():
    from precompute.fetch import fetch_parcels

    coords = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    full_page = [_feature(f"APN{i}", "MAIN ST", str(i), "CLEARLAKE OAKS", coords) for i in range(1000)]
    partial_page = [_feature("APN_LAST", "MAIN ST", "9999", "CLEARLAKE OAKS", coords)]
    responses = [_geojson_response(full_page), _geojson_response(partial_page)]
    with patch("precompute.fetch.requests.get", side_effect=responses) as mock_get:
        result, repaired_apns = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 1001
    assert repaired_apns == []
    assert mock_get.call_count == 2
    second_call_params = mock_get.call_args_list[1].kwargs["params"]
    assert second_call_params["resultOffset"] == 1000


def test_fetch_parcels_continues_on_exceeded_transfer_limit():
    """Regression test: pagination must honor exceededTransferLimit even if page is partial.

    Scenario: server's maxRecordCount is lower than our PAGE_SIZE (1000), so a page
    comes back with fewer records (e.g. 500) but exceededTransferLimit is true, meaning
    more data exists. The code must continue paging (not stop early based on page size).
    """
    from precompute.fetch import fetch_parcels

    coords = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    # First page: partial (500 records) but exceededTransferLimit=true
    partial_page_1 = [_feature(f"APN{i}", "MAIN ST", str(i), "CLEARLAKE OAKS", coords) for i in range(500)]
    # Second page: final partial (100 records) with exceededTransferLimit=false
    partial_page_2 = [_feature(f"APN{i}", "MAIN ST", str(i), "CLEARLAKE OAKS", coords) for i in range(500, 600)]
    responses = [
        _geojson_response(partial_page_1, exceeded_transfer_limit=True),
        _geojson_response(partial_page_2, exceeded_transfer_limit=False),
    ]
    with patch("precompute.fetch.requests.get", side_effect=responses) as mock_get:
        result, repaired_apns = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 600
    assert repaired_apns == []
    assert mock_get.call_count == 2
    second_call_params = mock_get.call_args_list[1].kwargs["params"]
    assert second_call_params["resultOffset"] == 1000


def test_fetch_roadways_parses_linestring_features():
    from precompute.fetch import fetch_roadways

    feature = {
        "type": "Feature",
        "properties": {"ROADNAME": "MAIN ST"},
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]},
    }
    with patch("precompute.fetch.requests.get", return_value=_geojson_response([feature])):
        result = fetch_roadways()

    assert len(result) == 1
    assert result[0]["roadname"] == "MAIN ST"
    assert result[0]["geometry"].length == 10


def test_fetch_roadways_drops_features_with_null_geometry():
    # Regression test: roadway features with no geometry carry no usable
    # information for clustering and previously flowed straight through into
    # match_roadway, where an all-None matches list could produce an empty
    # (rather than None) geometry and crash downstream. fetch_roadways must
    # filter them out.
    from precompute.fetch import fetch_roadways

    good_feature = {
        "type": "Feature",
        "properties": {"ROADNAME": "MAIN ST"},
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]},
    }
    null_geom_feature = {
        "type": "Feature",
        "properties": {"ROADNAME": "NO GEOM ST"},
        "geometry": None,
    }
    with patch(
        "precompute.fetch.requests.get",
        return_value=_geojson_response([good_feature, null_geom_feature]),
    ):
        result = fetch_roadways()

    assert len(result) == 1
    assert result[0]["roadname"] == "MAIN ST"


def test_fetch_parcels_raises_on_arcgis_error_payload():
    from precompute.fetch import fetch_parcels

    with patch(
        "precompute.fetch.requests.get",
        return_value=_geojson_response([], error={"code": 400, "message": "bad request"}),
    ):
        with pytest.raises(RuntimeError, match="ArcGIS query error"):
            fetch_parcels("CLEARLAKE OAKS")


def test_fetch_parcels_repairs_invalid_geometry_and_reports_apn():
    """Real Lake County data occasionally has self-intersecting ('bowtie') parcel polygons
    (digitizing artifacts). fetch_parcels must repair these via buffer(0) so downstream
    clustering (shapely unary_union) doesn't crash with a TopologyException, and must report
    which APNs were repaired so an operator can see what was altered before it's written to
    the database (mirrors the excluded-parcels visibility precompute/run.py already provides).
    """
    from precompute.fetch import fetch_parcels

    # Classic bowtie/hourglass self-intersecting polygon: shapely reports .is_valid == False.
    bowtie_coords = [[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]
    page = [_feature("APN_BOWTIE", "MAIN ST", "100", "CLEARLAKE OAKS", bowtie_coords)]
    with patch("precompute.fetch.requests.get", return_value=_geojson_response(page)):
        result, repaired_apns = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 1
    assert result[0]["geometry"].is_valid is True
    assert repaired_apns == ["APN_BOWTIE"]


def test_fetch_parcels_treats_empty_buffer_repair_result_as_missing_geometry():
    """A degenerate invalid ring (e.g. a zero-area self-intersecting/"bowtie"-like
    ring collapsed to a line) can repair to POLYGON EMPTY via buffer(0). is_valid
    is True for this but it's not usable geometry: e.g. .centroid on it raises
    GEOSException downstream. fetch_parcels must treat this the same as a missing
    geometry (geometry: None) so it flows into cluster.py's existing exclusion
    path instead of crashing later.
    """
    from shapely.geometry import Polygon

    from precompute.fetch import fetch_parcels

    # Verify assumption directly before building the test around it: this
    # degenerate ring collapses to an empty (but "valid") polygon after buffer(0).
    degenerate_coords = [(0, 0), (1, 1), (2, 2), (0, 0)]
    repaired = Polygon(degenerate_coords).buffer(0)
    assert repaired.is_empty is True
    assert repaired.is_valid is True

    page = [_feature("APN_EMPTY", "MAIN ST", "100", "CLEARLAKE OAKS", degenerate_coords)]
    with patch("precompute.fetch.requests.get", return_value=_geojson_response(page)):
        result, repaired_apns = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 1
    assert result[0]["geometry"] is None


def test_fetch_parcels_leaves_valid_geometry_unchanged():
    """Confirms the buffer(0) repair path is a no-op for already-valid geometry: the polygon
    passes through essentially unchanged, and no APN is reported as repaired.
    """
    from shapely.geometry import Polygon

    from precompute.fetch import fetch_parcels

    coords = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    page = [_feature("APN_VALID", "MAIN ST", "100", "CLEARLAKE OAKS", coords)]
    with patch("precompute.fetch.requests.get", return_value=_geojson_response(page)):
        result, repaired_apns = fetch_parcels("CLEARLAKE OAKS")

    assert result[0]["geometry"].equals(Polygon(coords))
    assert repaired_apns == []
