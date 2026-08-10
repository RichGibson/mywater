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
    for feat in features:
        props = feat["properties"]
        geom = shape(feat["geometry"]) if feat.get("geometry") else None
        if geom is not None and not geom.is_valid:
            # Real-world county parcel data occasionally has minor self-intersections
            # (e.g. digitizing artifacts). buffer(0) is the standard Shapely/GEOS idiom
            # to repair these without materially changing the polygon's shape.
            geom = geom.buffer(0)
        records.append(
            {
                "apn": props.get("APN"),
                "situsstr": (props.get("SITUSSTR") or "").strip(),
                "situsnum": props.get("SITUSNUM"),
                "situsfull": props.get("SITUSFULL"),
                "geometry": geom,
            }
        )
    return records


def fetch_roadways(base_url=PARCELS_MAPSERVER_URL):
    features = _query_all_features(f"{base_url}/1", "1=1", "ROADNAME")
    records = []
    for feat in features:
        props = feat["properties"]
        geom = shape(feat["geometry"]) if feat.get("geometry") else None
        records.append({"roadname": (props.get("ROADNAME") or "").strip(), "geometry": geom})
    return records
