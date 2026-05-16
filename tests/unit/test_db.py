import pytest
from banlog.db import open_db


def test_fresh_db_creates_schema_at_version_1(tmp_path):
    db = open_db(str(tmp_path / "test.db"))
    row = db.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == 1


def test_open_existing_db_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    open_db(path).close()
    db = open_db(path)
    assert db.execute("SELECT version FROM schema_version").fetchone()["version"] == 1


def test_future_schema_version_raises(tmp_path):
    path = str(tmp_path / "test.db")
    db = open_db(path)
    db.execute("UPDATE schema_version SET version = 99")
    db.commit()
    db.close()
    with pytest.raises(RuntimeError, match="downgrade"):
        open_db(path)


def test_in_memory_db_works():
    db = open_db(":memory:")
    assert db.execute("SELECT version FROM schema_version").fetchone()["version"] == 1


def test_insert_and_query_active_ip(tmp_path):
    db = open_db(str(tmp_path / "test.db"))
    db.execute(
        "INSERT INTO blocked_ips(ip, source, service, start_ts) VALUES (?, ?, ?, ?)",
        ("1.2.3.4", "turris", "ssh", 1000),
    )
    db.commit()
    row = db.execute(
        "SELECT ip FROM blocked_ips WHERE ip = '1.2.3.4' AND end_ts IS NULL"
    ).fetchone()
    assert row["ip"] == "1.2.3.4"


def test_close_ip_sets_end_ts(tmp_path):
    db = open_db(str(tmp_path / "test.db"))
    db.execute(
        "INSERT INTO blocked_ips(ip, source, service, start_ts) VALUES (?, ?, ?, ?)",
        ("1.2.3.4", "turris", "ssh", 1000),
    )
    db.commit()
    db.execute("UPDATE blocked_ips SET end_ts = 2000 WHERE ip = '1.2.3.4' AND end_ts IS NULL")
    db.commit()
    assert db.execute(
        "SELECT * FROM blocked_ips WHERE ip = '1.2.3.4' AND end_ts IS NULL"
    ).fetchone() is None
    assert db.execute(
        "SELECT end_ts FROM blocked_ips WHERE ip = '1.2.3.4'"
    ).fetchone()["end_ts"] == 2000


def test_history_multiple_rows_same_ip(tmp_path):
    db = open_db(str(tmp_path / "test.db"))
    for ts in (100, 200, 300):
        db.execute(
            "INSERT INTO blocked_ips(ip, source, service, start_ts, end_ts) VALUES (?, ?, ?, ?, ?)",
            ("1.2.3.4", "turris", "ssh", ts, ts + 50),
        )
    db.commit()
    rows = db.execute(
        "SELECT * FROM blocked_ips WHERE ip = '1.2.3.4' ORDER BY start_ts"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0]["start_ts"] == 100
