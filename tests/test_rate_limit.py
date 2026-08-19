from pathlib import Path

import pytest

from db import init_app_db
from precompute.load import connect as spatialite_connect


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "mywater_app.db"
    init_app_db(db_path)
    connection = spatialite_connect(str(db_path))
    yield connection
    connection.close()


def test_hash_identifier_is_deterministic_and_not_plaintext():
    from rate_limit import hash_identifier

    h1 = hash_identifier("1.2.3.4")
    h2 = hash_identifier("1.2.3.4")
    assert h1 == h2
    assert h1 != "1.2.3.4"


def test_hash_identifier_differs_for_different_inputs():
    from rate_limit import hash_identifier

    assert hash_identifier("1.2.3.4") != hash_identifier("5.6.7.8")


def test_is_rate_limited_false_when_under_threshold(conn):
    from rate_limit import is_rate_limited, record_submission

    ip_hash, cookie_id = "iphash1", "cookie1"
    for _ in range(4):
        record_submission(conn, ip_hash, cookie_id)
    assert is_rate_limited(conn, ip_hash, cookie_id, limit=5) is False


def test_is_rate_limited_true_when_ip_hits_threshold(conn):
    from rate_limit import is_rate_limited, record_submission

    ip_hash, cookie_id = "iphash1", "cookie1"
    for _ in range(5):
        record_submission(conn, ip_hash, cookie_id)
    assert is_rate_limited(conn, ip_hash, cookie_id, limit=5) is True


def test_is_rate_limited_true_when_cookie_hits_threshold_even_if_ip_differs(conn):
    from rate_limit import is_rate_limited, record_submission

    cookie_id = "shared_cookie"
    for i in range(5):
        record_submission(conn, f"iphash{i}", cookie_id)
    assert is_rate_limited(conn, "some_new_iphash", cookie_id, limit=5) is True


def test_is_rate_limited_ignores_entries_older_than_24_hours(conn):
    from rate_limit import is_rate_limited

    ip_hash, cookie_id = "iphash1", "cookie1"
    old_timestamp = "2000-01-01T00:00:00"
    for _ in range(5):
        conn.execute(
            "INSERT INTO submission_log (ip_hash, cookie_id, created_at) VALUES (?, ?, ?)",
            (ip_hash, cookie_id, old_timestamp),
        )
    conn.commit()
    assert is_rate_limited(conn, ip_hash, cookie_id, limit=5) is False
