from shapely.ops import linemerge, unary_union

TARGET_CLUSTER_SIZE = 8
MIN_CLUSTER_SIZE = 6
MAX_CLUSTER_SIZE = 10


def bucket_parcels(ordered_parcels, target=TARGET_CLUSTER_SIZE, max_size=MAX_CLUSTER_SIZE):
    clusters = []
    n = len(ordered_parcels)
    i = 0
    while i < n:
        remaining = n - i
        if remaining <= max_size:
            clusters.append(ordered_parcels[i:])
            i = n
        else:
            clusters.append(ordered_parcels[i : i + target])
            i += target

    # Rebalance an avoidable trailing remainder: if the last bucket is smaller
    # than MIN_CLUSTER_SIZE but there's a preceding full-target bucket to borrow
    # from, split the combined total of the last two buckets roughly evenly
    # instead of leaving a tiny tail. A single short bucket is only left in
    # place when the street itself is too small overall to avoid it (i.e.
    # there's no preceding bucket to redistribute with).
    if len(clusters) >= 2:
        last = clusters[-1]
        prev = clusters[-2]
        remainder = len(last)
        if 0 < remainder < MIN_CLUSTER_SIZE and len(prev) > MIN_CLUSTER_SIZE:
            combined = prev + last
            split = len(combined) // 2
            clusters[-2] = combined[:split]
            clusters[-1] = combined[split:]

    return clusters


def match_roadway(street_name, roadways):
    matches = [
        r["geometry"]
        for r in roadways
        if r["roadname"].strip().upper() == street_name.strip().upper()
    ]
    if not matches:
        return None
    union = unary_union(matches)
    if union.geom_type == "LineString":
        return union
    merged = linemerge(union)
    # Guard against all-None/empty geometry inputs: unary_union of an all-None
    # (or otherwise degenerate) matches list can yield GEOMETRYCOLLECTION EMPTY,
    # and linemerge of that is an empty GeometryCollection rather than a
    # LineString/MultiLineString. Treat that the same as "no match found"
    # rather than returning an empty geometry that crashes downstream
    # (e.g. roadway_line.interpolate() in build_cluster_record).
    if merged.is_empty:
        return None
    # Detect disjoint segments: if merged result is MultiLineString (segments didn't merge),
    # return None to use fallback path (situsnum ordering, union centroid) instead of
    # silently producing wrong geography via incorrect projection/interpolation on MultiLineString
    if merged.geom_type == "MultiLineString":
        return None
    return merged


def order_parcels_along_street(parcels, roadway_line):
    if roadway_line is not None:
        return sorted(parcels, key=lambda p: roadway_line.project(p["geometry"].centroid))

    def numeric_key(p):
        try:
            return int(p["situsnum"])
        except (TypeError, ValueError):
            return 0

    return sorted(parcels, key=numeric_key)


def build_cluster_record(cluster_parcels, roadway_line):
    geoms = [p["geometry"] for p in cluster_parcels]
    union_geom = unary_union(geoms)
    if roadway_line is not None:
        distances = [roadway_line.project(p["geometry"].centroid) for p in cluster_parcels]
        mid_distance = (min(distances) + max(distances)) / 2
        centroid_point = roadway_line.interpolate(mid_distance)
    else:
        centroid_point = union_geom.centroid
    return {
        "geometry": union_geom,
        "centroid_lat": centroid_point.y,
        "centroid_lng": centroid_point.x,
        "parcel_count": len(cluster_parcels),
        "members": cluster_parcels,
    }


def cluster_parcels_by_street(parcels, roadways):
    valid, excluded = [], []
    for p in parcels:
        if p.get("geometry") is None or not p.get("situsstr"):
            excluded.append(p.get("apn"))
        else:
            valid.append(p)

    by_street = {}
    for p in valid:
        by_street.setdefault(p["situsstr"], []).append(p)

    clusters = []
    for street_name, street_parcels in by_street.items():
        roadway_line = match_roadway(street_name, roadways)
        ordered = order_parcels_along_street(street_parcels, roadway_line)
        for bucket in bucket_parcels(ordered):
            record = build_cluster_record(bucket, roadway_line)
            record["street_name"] = street_name
            clusters.append(record)

    outlier_indices = [
        i
        for i, c in enumerate(clusters)
        if not (MIN_CLUSTER_SIZE <= c["parcel_count"] <= MAX_CLUSTER_SIZE)
    ]
    return clusters, excluded, outlier_indices
