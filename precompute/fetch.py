import requests
from shapely.geometry import shape

PARCELS_MAPSERVER_URL = "https://gis.lakecountyca.gov/server/rest/services/Parcels/MapServer"
PAGE_SIZE = 1000


def _query_all_features(layer_url, where, out_fields):
    features = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "geojson",
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
            "orderByFields": "OBJECTID",
        }
        resp = requests.get(f"{layer_url}/query", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"ArcGIS query error: {data['error']}")
        page_features = data.get("features", [])
        features.extend(page_features)
        # Use exceededTransferLimit as primary signal (per Esri documentation).
        # If true, continue paging regardless of page size.
        # If false/absent, stop — but check page size as fallback for older servers that omit the flag.
        exceeded = data.get("exceededTransferLimit")
        if exceeded:
            offset += PAGE_SIZE
        elif len(page_features) < PAGE_SIZE:
            break
        else:
            offset += PAGE_SIZE
    return features


def fetch_parcels(community_name, base_url=PARCELS_MAPSERVER_URL):
    where = f"SITUSFULL LIKE '%{community_name}%'"
    features = _query_all_features(f"{base_url}/0", where, "APN,SITUSSTR,SITUSNUM,SITUSFULL")
    records = []
    repaired_apns = []
    for feat in features:
        props = feat["properties"]
        apn = props.get("APN")
        geom = shape(feat["geometry"]) if feat.get("geometry") else None
        if geom is not None and not geom.is_valid:
            # Real-world county parcel data occasionally has minor self-intersections
            # (e.g. digitizing artifacts). buffer(0) is the standard Shapely/GEOS idiom
            # to repair these without materially changing the polygon's shape.
            geom = geom.buffer(0)
            repaired_apns.append(apn)
            if geom.is_empty:
                # A degenerate invalid ring (e.g. zero-area self-intersection) can
                # collapse to POLYGON EMPTY after repair. is_valid is True for this
                # but it's not usable geometry (e.g. its centroid crashes downstream
                # with GEOSException). Treat it the same as missing geometry so it
                # flows into the existing "geometry is None" exclusion path.
                geom = None
        records.append(
            {
                "apn": apn,
                "situsstr": (props.get("SITUSSTR") or "").strip(),
                "situsnum": props.get("SITUSNUM"),
                "situsfull": props.get("SITUSFULL"),
                "geometry": geom,
            }
        )
    return records, repaired_apns


def fetch_roadways(base_url=PARCELS_MAPSERVER_URL):
    features = _query_all_features(f"{base_url}/1", "1=1", "ROADNAME")
    records = []
    for feat in features:
        # Features with no geometry carry no usable information for clustering
        # (match_roadway would otherwise feed None into unary_union, which can
        # yield an empty geometry that downstream code mishandles). Drop them.
        if not feat.get("geometry"):
            continue
        props = feat["properties"]
        geom = shape(feat["geometry"])
        records.append({"roadname": (props.get("ROADNAME") or "").strip(), "geometry": geom})
    return records
