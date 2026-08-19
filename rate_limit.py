import hashlib
import os
from datetime import datetime, timedelta, timezone

RATE_LIMIT_PER_DAY = int(os.environ.get("RATE_LIMIT_PER_DAY", "5"))
_RATE_LIMIT_PEPPER = os.environ.get("RATE_LIMIT_PEPPER", "")


def hash_identifier(value):
    return hashlib.sha256((_RATE_LIMIT_PEPPER + value).encode("utf-8")).hexdigest()


def _count_recent(conn, column, value, since_iso):
    row = conn.execute(
        f"SELECT COUNT(*) FROM submission_log WHERE {column} = ? AND created_at >= ?",
        (value, since_iso),
    ).fetchone()
    return row[0]


def is_rate_limited(conn, ip_hash, cookie_id, limit=None):
    if limit is None:
        limit = RATE_LIMIT_PER_DAY
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    ip_count = _count_recent(conn, "ip_hash", ip_hash, since)
    cookie_count = _count_recent(conn, "cookie_id", cookie_id, since)
    return ip_count >= limit or cookie_count >= limit


def record_submission(conn, ip_hash, cookie_id):
    conn.execute(
        "INSERT INTO submission_log (ip_hash, cookie_id) VALUES (?, ?)",
        (ip_hash, cookie_id),
    )
    conn.commit()
