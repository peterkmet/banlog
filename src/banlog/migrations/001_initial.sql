CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_ts INTEGER NOT NULL
);

CREATE TABLE blocked_ips (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ip          TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    service     TEXT    NOT NULL,
    start_ts    INTEGER NOT NULL,
    end_ts      INTEGER,
    metadata    TEXT
);

CREATE INDEX idx_active   ON blocked_ips(ip, source, service) WHERE end_ts IS NULL;
CREATE INDEX idx_ip       ON blocked_ips(ip);
CREATE INDEX idx_service  ON blocked_ips(service);
CREATE INDEX idx_start_ts ON blocked_ips(start_ts);

CREATE TABLE sync_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    started_ts  INTEGER NOT NULL,
    finished_ts INTEGER,
    status      TEXT    NOT NULL,
    added       INTEGER DEFAULT 0,
    removed     INTEGER DEFAULT 0,
    total       INTEGER DEFAULT 0,
    error       TEXT
);

INSERT INTO schema_version(version, applied_ts) VALUES (1, strftime('%s', 'now'));
