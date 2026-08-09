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
        result = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 1
    assert result[0]["apn"] == "APN1"
    assert result[0]["situsstr"] == "MAIN ST"
    assert result[0]["geometry"] is not None
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
        result = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 1001
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
        result = fetch_parcels("CLEARLAKE OAKS")

    assert len(result) == 600
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


def test_fetch_parcels_raises_on_arcgis_error_payload():
    from precompute.fetch import fetch_parcels

    with patch(
        "precompute.fetch.requests.get",
        return_value=_geojson_response([], error={"code": 400, "message": "bad request"}),
    ):
        with pytest.raises(RuntimeError, match="ArcGIS query error"):
            fetch_parcels("CLEARLAKE OAKS")
