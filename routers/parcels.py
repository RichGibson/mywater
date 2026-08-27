import json

from fastapi import APIRouter, Depends

from db import get_db

router = APIRouter()


@router.get("/parcels.geojson")
def parcels_geojson(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT id, apn,  situsstr,concat(situsnum,' ',situsstr) as street_address, cluster_id, centroid_lat, centroid_lng, AsGeoJSON(geometry) "
        "FROM parcels_db.parcels"
    ).fetchall()
    features = []
    for pid, apn, situsstr, street_address, cluster_id, lat, lng, geom_json in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(geom_json),
                "properties": {
                    "id": pid,
                    "apn": apn,
                    "situsstr": situsstr,
                    "street_address": street_address,
                    "cluster_id": cluster_id,
                    "centroid_lat": lat,
                    "centroid_lng": lng,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


@router.get("/clusters.geojson")
def clusters_geojson(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT id, street_name, centroid_lat, centroid_lng, parcel_count, anonymization_safe, "
        "AsGeoJSON(geometry) FROM parcels_db.parcel_clusters"
    ).fetchall()
    features = []
    for cid, street_name, lat, lng, parcel_count, safe, geom_json in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(geom_json),
                "properties": {
                    "id": cid,
                    "street_name": street_name,
                    "centroid_lat": lat,
                    "centroid_lng": lng,
                    "parcel_count": parcel_count,
                    "anonymization_safe": bool(safe),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
