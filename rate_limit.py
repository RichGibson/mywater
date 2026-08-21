import hashlib
import os
from datetime import datetime, timedelta, timezone


def _get_rate_limit_per_day():
    return int(os.environ.get("RATE_LIMIT_PER_DAY", "5"))


def _get_pepper():
    pepper = os.environ.get("RATE_LIMIT_PEPPER")
    if not pepper:
        raise RuntimeError(
            "RATE_LIMIT_PEPPER environment variable must be set to a random string "
            "before rate limiting can be used — an unset pepper makes IP hashes "
            "trivially reversible. See .env.example."
        )
    return pepper


def hash_identifier(value):
    pepper = _get_pepper()
    return hashlib.sha256((pepper + value).encode("utf-8")).hexdigest()


def _count_recent(conn, column, value, since_iso):
    row = conn.execute(
        f"SELECT COUNT(*) FROM submission_log WHERE {column} = ? AND created_at >= ?",
        (value, since_iso),
    ).fetchone()
    return row[0]


def is_rate_limited(conn, ip_hash, cookie_id, limit=None):
    if limit is None:
        limit = _get_rate_limit_per_day()
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    ip_count = _count_recent(conn, "ip_hash", ip_hash, since)
    cookie_count = _count_recent(conn, "cookie_id", cookie_id, since)
    return ip_count >= limit or cookie_count >= limit


def record_submission(conn, ip_hash, cookie_id):
    # Coarsened to hour granularity (rather than relying on the schema's
    # second-granularity default) so submission_log.created_at can't be
    # rejoined precisely to reports.created_at. Without this, anyone with DB
    # access could match an obscured report's insert-time timestamp to the
    # submission_log row created microseconds later, recover the ip_hash/
    # cookie_id behind it, and then find that same visitor's other reports
    # — including a non-obscured one naming their exact parcel. This defeats
    # the "anonymous even via a DB leak" guarantee for obscured reports.
    hour_bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00:00")
    conn.execute(
        "INSERT INTO submission_log (ip_hash, cookie_id, created_at) VALUES (?, ?, ?)",
        (ip_hash, cookie_id, hour_bucket),
    )
    conn.commit()
