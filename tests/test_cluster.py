import pytest
from shapely.geometry import LineString, Polygon

from precompute.cluster import (
    MAX_CLUSTER_SIZE,
    MIN_CLUSTER_SIZE,
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
    # Regression test for the anonymization-safety fix: a naive greedy chunker
    # produces [8, 8, 4] here (a 4-parcel tail, which is below MIN_CLUSTER_SIZE
    # and defeats the anonymization guarantee). The fix must rebalance the
    # final two buckets so no avoidable bucket falls below MIN_CLUSTER_SIZE.
    parcels = [{"apn": str(i)} for i in range(20)]
    buckets = bucket_parcels(parcels, target=8, max_size=10)
    sizes = [len(b) for b in buckets]
    assert sizes == [8, 6, 6]
    assert all(MIN_CLUSTER_SIZE <= s <= MAX_CLUSTER_SIZE for s in sizes)
    assert sum(sizes) == 20
    # No parcel lost or duplicated across buckets.
    all_apns = sorted(int(p["apn"]) for b in buckets for p in b)
    assert all_apns == list(range(20))


def test_bucket_parcels_keeps_single_bucket_when_under_max():
    parcels = [{"apn": str(i)} for i in range(9)]
    buckets = bucket_parcels(parcels, target=8, max_size=10)
    assert [len(b) for b in buckets] == [9]


def test_bucket_parcels_rebalances_large_street_trailing_remainder():
    # 204 parcels: 204 = 25*8 + 4, so a naive greedy chunker produces
    # 25 buckets of 8 followed by a 4-parcel tail. Since the street is large
    # enough to redistribute (there's a full preceding bucket to borrow from),
    # no bucket should end up below MIN_CLUSTER_SIZE.
    parcels = [{"apn": str(i)} for i in range(204)]
    buckets = bucket_parcels(parcels, target=8, max_size=10)
    sizes = [len(b) for b in buckets]
    assert sum(sizes) == 204
    assert all(MIN_CLUSTER_SIZE <= s <= MAX_CLUSTER_SIZE for s in sizes)
    assert sizes[-2:] == [6, 6]


def test_match_roadway_finds_case_insensitive_match():
    line = LineString([(0, 0), (10, 0)])
    roadways = [{"roadname": "Main St", "geometry": line}]
    result = match_roadway("MAIN ST", roadways)
    assert result is not None
    assert result.equals(line)


def test_match_roadway_returns_none_when_no_match():
    roadways = [{"roadname": "Elm St", "geometry": LineString([(0, 0), (10, 0)])}]
    assert match_roadway("MAIN ST", roadways) is None


def test_match_roadway_returns_none_when_all_matches_have_null_geometry():
    # Regression test: roadway features with no geometry (e.g. from
    # fetch_roadways before it filtered them, or any other source) can leave
    # match_roadway with an all-None matches list. unary_union(all-None)
    # yields GEOMETRYCOLLECTION EMPTY, and linemerge of that is an empty
    # GeometryCollection - a type match_roadway's LineString/MultiLineString
    # checks don't catch. Must return None (same as "no match found") instead
    # of an empty geometry that would crash downstream interpolate() calls.
    roadways = [
        {"roadname": "Main St", "geometry": None},
        {"roadname": "Main St", "geometry": None},
    ]
    result = match_roadway("MAIN ST", roadways)
    assert result is None


def test_match_roadway_returns_none_for_disjoint_same_named_segments():
    # Regression test: disjoint segments of same street name should return None
    # to avoid silently producing wrong geography via MultiLineString projection
    roadways = [
        {"roadname": "Main St", "geometry": LineString([(0, 0), (2, 0)])},
        {"roadname": "Main St", "geometry": LineString([(100, 0), (102, 0)])},
    ]
    result = match_roadway("MAIN ST", roadways)
    assert result is None


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


def test_cluster_parcels_by_street_handles_disjoint_segments_via_fallback():
    # Regression test: when roadway segments are disjoint (don't merge),
    # cluster_parcels_by_street should still cluster correctly using fallback
    # path (situsnum ordering, union centroid) instead of broken MultiLineString projection
    disjoint_roadways = [
        {"roadname": "Split St", "geometry": LineString([(0, 0), (2, 0)])},
        {"roadname": "Split St", "geometry": LineString([(100, 0), (102, 0)])},
    ]
    parcels = [
        {
            "apn": f"P{i}",
            "situsstr": "Split St",
            "situsnum": str(100 + i),
            "geometry": _square(i, 0.1),
        }
        for i in range(8)
    ]
    clusters, excluded, outlier_indices = cluster_parcels_by_street(parcels, disjoint_roadways)
    # Should still produce one cluster via situsnum fallback ordering
    assert len(clusters) == 1
    assert clusters[0]["parcel_count"] == 8
    # Centroid should be computed via union centroid (not broken street midpoint)
    assert clusters[0]["centroid_lng"] == pytest.approx(3.5, abs=0.01)
