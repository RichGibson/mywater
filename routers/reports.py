import uuid
from typing import Optional

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


def _parcel_exists(conn, parcel_id):
    row = conn.execute("SELECT 1 FROM parcels_db.parcels WHERE id = ?", (parcel_id,)).fetchone()
    return row is not None


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

    if report.obscured:
        if not _cluster_is_safe(conn, report.cluster_id):
            raise HTTPException(
                status_code=400, detail="cluster_id is not a valid, anonymization-safe cluster"
            )
    else:
        if not _parcel_exists(conn, report.parcel_id):
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

    cur = conn.execute(
        """
        INSERT INTO reports (
            report_type, obscured, parcel_id, cluster_id, free_text, photo_url,
            taste, smell, color, pressure, event_subtype, ongoing
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report.report_type,
            int(report.obscured),
            report.parcel_id,
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
        COOKIE_NAME, cookie_id, max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax"
    )

    return {"id": cur.lastrowid, "report_type": report.report_type}
