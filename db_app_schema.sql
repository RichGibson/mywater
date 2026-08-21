CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL CHECK (report_type IN ('event', 'quality')),
    obscured INTEGER NOT NULL CHECK (obscured IN (0, 1)),
    parcel_id INTEGER,
    parcel_apn TEXT,
    cluster_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    free_text TEXT,
    photo_url TEXT,
    taste TEXT CHECK (taste IN ('good', 'off', 'bad')),
    smell TEXT CHECK (smell IN ('good', 'off', 'bad')),
    color TEXT CHECK (color IN ('good', 'off', 'bad')),
    pressure TEXT CHECK (pressure IN ('good', 'off', 'bad')),
    event_subtype TEXT CHECK (event_subtype IN ('main_break', 'outage', 'boil_notice', 'other')),
    ongoing INTEGER CHECK (ongoing IN (0, 1)),
    CHECK (length(free_text) <= 500),
    CHECK (
        (obscured = 0 AND parcel_id IS NOT NULL AND cluster_id IS NULL)
        OR (obscured = 1 AND cluster_id IS NOT NULL AND parcel_id IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at);

CREATE TABLE IF NOT EXISTS submission_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_hash TEXT NOT NULL,
    cookie_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_submission_log_ip_hash_created_at ON submission_log(ip_hash, created_at);
CREATE INDEX IF NOT EXISTS idx_submission_log_cookie_id_created_at ON submission_log(cookie_id, created_at);
