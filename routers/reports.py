import json
import uuid
from datetime import datetime
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Request, Response, UploadFile

from db import get_db
from models import ReportCreate
from photos import PhotoValidationError, upload_photo
from rate_limit import hash_identifier, is_rate_limited, record_submission

router = APIRouter()

COOKIE_NAME = "mywater_id"


def _client_ip(request: Request):
    return request.headers.get(
        "cf-connecting-ip", request.client.host if request.client else "unknown"
    )


def _get_parcel_apn(conn, parcel_id):
    """Look up a parcel's stable APN by its (unstable) precompute-assigned id.

    Returns the apn string, or None if the parcel does not exist. parcel_id
    is not stable across precompute rebuilds, so callers must persist the
    returned apn (not just parcel_id) for anything that needs to survive one.
    """
    row = conn.execute(
        "SELECT apn FROM parcels_db.parcels WHERE id = ?", (parcel_id,)
    ).fetchone()
    return row[0] if row is not None else None


def _cluster_is_safe(conn, cluster_id):
    row = conn.execute(
        "SELECT anonymization_safe FROM parcels_db.parcel_clusters WHERE id = ?",
        (cluster_id,),
    ).fetchone()
    return row is not None and row[0] == 1


@router.post("/reports")
async def create_report(
    request: Request,
    response: Response,
    report_type: str = Form(...),
    obscured: bool = Form(...),
    parcel_id: Optional[int] = Form(None),
    cluster_id: Optional[int] = Form(None),
    free_text: Optional[str] = Form(None),
    taste: Optional[str] = Form(None),
    smell: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    pressure: Optional[str] = Form(None),
    event_subtype: Optional[str] = Form(None),
    ongoing: Optional[bool] = Form(None),
    photo: Optional[UploadFile] = File(None),
    mywater_id: Optional[str] = Cookie(None),
    conn=Depends(get_db),
):
    try:
        report = ReportCreate(
            report_type=report_type,
            obscured=obscured,
            parcel_id=parcel_id,
            cluster_id=cluster_id,
            free_text=free_text,
            taste=taste,
            smell=smell,
            color=color,
            pressure=pressure,
            event_subtype=event_subtype,
            ongoing=ongoing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    parcel_apn = None
    if report.obscured:
        if not _cluster_is_safe(conn, report.cluster_id):
            raise HTTPException(
                status_code=400, detail="cluster_id is not a valid, anonymization-safe cluster"
            )
    else:
        parcel_apn = _get_parcel_apn(conn, report.parcel_id)
        if parcel_apn is None:
            raise HTTPException(status_code=400, detail="parcel_id does not exist")

    cookie_id = mywater_id or str(uuid.uuid4())
    ip_hash = hash_identifier(_client_ip(request))
    cookie_hash = hash_identifier(cookie_id)

    if is_rate_limited(conn, ip_hash, cookie_hash):
        raise HTTPException(
            status_code=429, detail="you've reached today's report limit — try again tomorrow"
        )

    photo_url = None
    if photo is not None and photo.filename:
        content = await photo.read()
        try:
            photo_url = upload_photo(content, photo.content_type)
        except PhotoValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except (KeyError, BotoCoreError, ClientError):
            # KeyError: R2 credentials/config missing from the environment.
            # BotoCoreError/ClientError: R2 network or API failure (e.g.
            # EndpointConnectionError, auth rejection). Per the design
            # spec's Error Handling section, a photo upload failure must
            # block submission with a clear error rather than a bare 500 —
            # the client can still retry without a photo.
            raise HTTPException(
                status_code=400,
                detail="couldn't upload photo right now; try again or submit without a photo",
            )

    cur = conn.execute(
        """
        INSERT INTO reports (
            report_type, obscured, parcel_id, parcel_apn, cluster_id, free_text, photo_url,
            taste, smell, color, pressure, event_subtype, ongoing
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report.report_type,
            int(report.obscured),
            report.parcel_id,
            parcel_apn,
            report.cluster_id,
            report.free_text,
            photo_url,
            report.taste,
            report.smell,
            report.color,
            report.pressure,
            report.event_subtype,
            int(report.ongoing) if report.ongoing is not None else None,
        ),
    )
    conn.commit()
    record_submission(conn, ip_hash, cookie_hash)

    response.set_cookie(
        COOKIE_NAME,
        cookie_id,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="lax",
        secure=True,
    )

    return {"id": cur.lastrowid, "report_type": report.report_type}


def _parse_date_param(value, param_name):
    """Validate an ISO 8601 date/datetime query param, fail loudly on garbage.

    Silently ignoring a malformed since/until would produce a wrong-but-200
    response instead of a clear error, so we 422 rather than let bad input
    fall through to the query.
    """
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"{param_name} must be an ISO 8601 date or datetime string",
        )
    if len(value) == 10:
        # Date-only (YYYY-MM-DD): normalize to end-of-day so "until=2026-08-20"
        # includes reports created any time that day, not just at midnight.
        return f"{value}T23:59:59"
    return value


@router.get("/reports.geojson")
def reports_geojson(since: Optional[str] = None, until: Optional[str] = None, conn=Depends(get_db)):
    if since is not None:
        since = _parse_date_param(since, "since")
    if until is not None:
        until = _parse_date_param(until, "until")

    query = """
        SELECT
            r.id, r.report_type, r.obscured, r.created_at, r.free_text, r.photo_url,
            r.taste, r.smell, r.color, r.pressure, r.event_subtype, r.ongoing,
            CASE WHEN r.obscured = 1 THEN pc.centroid_lat ELSE p.centroid_lat END AS lat,
            CASE WHEN r.obscured = 1 THEN pc.centroid_lng ELSE p.centroid_lng END AS lng,
            CASE WHEN r.obscured = 1 THEN pc.street_name ELSE NULL END AS cluster_street_name
        FROM reports r
        LEFT JOIN parcels_db.parcels p ON r.obscured = 0 AND p.apn = r.parcel_apn
        LEFT JOIN parcels_db.parcel_clusters pc
            ON r.obscured = 1 AND pc.id = r.cluster_id AND pc.anonymization_safe = 1
        WHERE 1 = 1
    """
    params = []
    if since:
        query += " AND r.created_at >= ?"
        params.append(since)
    if until:
        query += " AND r.created_at <= ?"
        params.append(until)
    query += " ORDER BY r.created_at DESC, r.id DESC"

    rows = conn.execute(query, params).fetchall()
    features = []
    for row in rows:
        (
            rid, report_type, obscured, created_at, free_text, photo_url,
            taste, smell, color, pressure, event_subtype, ongoing,
            lat, lng, cluster_street_name,
        ) = row
        properties = {
            "id": rid,
            "report_type": report_type,
            "obscured": bool(obscured),
            "created_at": created_at,
            "free_text": free_text,
            # Obscured reports never publish photo_url: an uploaded phone
            # photo can carry GPS EXIF data, so publishing its URL would let
            # anyone recover the exact location this report is meant to hide,
            # even though every other field is properly anonymized.
            "photo_url": photo_url if not obscured else None,
            "taste": taste,
            "smell": smell,
            "color": color,
            "pressure": pressure,
            "event_subtype": event_subtype,
            "ongoing": bool(ongoing) if ongoing is not None else None,
        }
        if obscured:
            properties["location_label"] = (
                f"area near {cluster_street_name}" if cluster_street_name else "area near unknown street"
            )
        geometry = None
        if lat is not None and lng is not None:
            geometry = {"type": "Point", "coordinates": [lng, lat]}
        features.append({"type": "Feature", "geometry": geometry, "properties": properties})
    return {"type": "FeatureCollection", "features": features}
