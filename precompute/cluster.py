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
    return linemerge(union)


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
