import pytest
from shapely.geometry import LineString, Polygon

from precompute.cluster import (
    bucket_parcels,
    build_cluster_record,
    cluster_parcels_by_street,
    match_roadway,
    order_parcels_along_street,
)


def _square(cx, cy, size=0.2):
    return Polygon(
        [
            (cx - size / 2, cy - size / 2),
            (cx + size / 2, cy - size / 2),
            (cx + size / 2, cy + size / 2),
            (cx - size / 2, cy + size / 2),
        ]
    )


def test_bucket_parcels_splits_evenly_sized_street_into_target_groups():
    parcels = [{"apn": str(i)} for i in range(16)]
    buckets = bucket_parcels(parcels, target=8, max_size=10)
    assert [len(b) for b in buckets] == [8, 8]


def test_bucket_parcels_folds_small_remainder_into_last_bucket():
    parcels = [{"apn": str(i)} for i in range(20)]
    buckets = bucket_parcels(parcels, target=8, max_size=10)
    assert [len(b) for b in buckets] == [8, 8, 4]


def test_bucket_parcels_keeps_single_bucket_when_under_max():
    parcels = [{"apn": str(i)} for i in range(9)]
    buckets = bucket_parcels(parcels, target=8, max_size=10)
    assert [len(b) for b in buckets] == [9]


def test_match_roadway_finds_case_insensitive_match():
    line = LineString([(0, 0), (10, 0)])
    roadways = [{"roadname": "Main St", "geometry": line}]
    result = match_roadway("MAIN ST", roadways)
    assert result is not None
    assert result.equals(line)


def test_match_roadway_returns_none_when_no_match():
    roadways = [{"roadname": "Elm St", "geometry": LineString([(0, 0), (10, 0)])}]
    assert match_roadway("MAIN ST", roadways) is None


def test_order_parcels_along_street_orders_by_projected_distance():
    line = LineString([(0, 0), (10, 0)])
    parcels = [
        {"apn": "C", "geometry": _square(7, 0.1), "situsnum": "300"},
        {"apn": "A", "geometry": _square(1, 0.1), "situsnum": "100"},
        {"apn": "B", "geometry": _square(4, 0.1), "situsnum": "200"},
    ]
    ordered = order_parcels_along_street(parcels, line)
    assert [p["apn"] for p in ordered] == ["A", "B", "C"]


def test_order_parcels_along_street_falls_back_to_situsnum_without_roadway():
    parcels = [
        {"apn": "C", "situsnum": "300", "geometry": _square(7, 0.1)},
        {"apn": "A", "situsnum": "100", "geometry": _square(1, 0.1)},
        {"apn": "B", "situsnum": "200", "geometry": _square(4, 0.1)},
    ]
    ordered = order_parcels_along_street(parcels, None)
    assert [p["apn"] for p in ordered] == ["A", "B", "C"]


def test_build_cluster_record_centroid_is_street_midpoint_of_members():
    line = LineString([(0, 0), (10, 0)])
    parcels = [
        {"apn": "A", "geometry": _square(2, 0.1)},
        {"apn": "B", "geometry": _square(4, 0.1)},
    ]
    record = build_cluster_record(parcels, line)
    assert record["parcel_count"] == 2
    assert record["centroid_lng"] == pytest.approx(3.0, abs=0.01)
    assert record["centroid_lat"] == pytest.approx(0.0, abs=0.01)
    assert record["members"] == parcels


def test_build_cluster_record_falls_back_to_union_centroid_without_roadway():
    parcels = [
        {"apn": "A", "geometry": _square(0, 0)},
        {"apn": "B", "geometry": _square(2, 0)},
    ]
    record = build_cluster_record(parcels, None)
    assert record["centroid_lng"] == pytest.approx(1.0, abs=0.01)


def test_cluster_parcels_by_street_excludes_parcels_missing_geometry_or_street():
    line = LineString([(0, 0), (10, 0)])
    roadways = [{"roadname": "MAIN ST", "geometry": line}]
    parcels = [
        {"apn": "A", "situsstr": "MAIN ST", "situsnum": "100", "geometry": _square(1, 0.1)},
        {"apn": "B", "situsstr": "MAIN ST", "situsnum": "200", "geometry": _square(2, 0.1)},
        {"apn": "MISSING_GEOM", "situsstr": "MAIN ST", "situsnum": "300", "geometry": None},
        {"apn": "MISSING_STREET", "situsstr": "", "situsnum": "400", "geometry": _square(4, 0.1)},
    ]
    clusters, excluded, outliers = cluster_parcels_by_street(parcels, roadways)
    assert set(excluded) == {"MISSING_GEOM", "MISSING_STREET"}
    assert sum(c["parcel_count"] for c in clusters) == 2


def test_cluster_parcels_by_street_flags_small_street_as_outlier():
    line = LineString([(0, 0), (10, 0)])
    roadways = [{"roadname": "SHORT LN", "geometry": line}]
    parcels = [
        {
            "apn": f"P{i}",
            "situsstr": "SHORT LN",
            "situsnum": str(100 + i),
            "geometry": _square(i, 0.1),
        }
        for i in range(3)
    ]
    clusters, excluded, outlier_indices = cluster_parcels_by_street(parcels, roadways)
    assert len(clusters) == 1
    assert clusters[0]["parcel_count"] == 3
    assert outlier_indices == [0]


def test_cluster_parcels_by_street_does_not_flag_target_sized_cluster():
    line = LineString([(0, 0), (10, 0)])
    roadways = [{"roadname": "LONG LN", "geometry": line}]
    parcels = [
        {
            "apn": f"P{i}",
            "situsstr": "LONG LN",
            "situsnum": str(100 + i),
            "geometry": _square(i, 0.1),
        }
        for i in range(8)
    ]
    clusters, excluded, outlier_indices = cluster_parcels_by_street(parcels, roadways)
    assert len(clusters) == 1
    assert outlier_indices == []
