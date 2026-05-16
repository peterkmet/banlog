import time
import pytest
from banlog.config import Config, FeedConfig, ServiceConfig
from banlog.sync import run_sync


def make_config(**feeds: dict) -> Config:
    result: dict[str, FeedConfig] = {}
    for name, data in feeds.items():
        services = {svc: ServiceConfig(enabled=en) for svc, en in data["services"].items()}
        result[name] = FeedConfig(
            name=name,
            type="turris",
            url=f"http://example.com/{name}.csv",
            refresh_minutes=60,
            services=services,
        )
    return Config(feeds=result)


def test_sync_adds_new_ips(db, monkeypatch):
    config = make_config(turris={"services": {"ssh": True}})
    monkeypatch.setattr("banlog.feeds.turris.TurrisFeed.fetch", lambda self, url: b"1.2.3.4,tag\n5.6.7.8,tag\n")
    monkeypatch.setattr("banlog.nft.replace_set", lambda svc, ips: None)

    report = run_sync(config, db)

    active = {r["ip"] for r in db.execute("SELECT ip FROM blocked_ips WHERE end_ts IS NULL")}
    assert active == {"1.2.3.4", "5.6.7.8"}
    assert report.results[0].added == 2
    assert report.results[0].status == "success"


def test_sync_removes_absent_ips(db, monkeypatch):
    now = int(time.time())
    db.execute("INSERT INTO blocked_ips(ip, source, service, start_ts) VALUES (?, ?, ?, ?)",
               ("9.9.9.9", "turris", "ssh", now - 100))
    db.commit()
    config = make_config(turris={"services": {"ssh": True}})
    monkeypatch.setattr("banlog.feeds.turris.TurrisFeed.fetch", lambda self, url: b"1.2.3.4,tag\n")
    monkeypatch.setattr("banlog.nft.replace_set", lambda svc, ips: None)

    report = run_sync(config, db)

    assert db.execute("SELECT * FROM blocked_ips WHERE ip='9.9.9.9' AND end_ts IS NOT NULL").fetchone()
    assert report.results[0].removed == 1


def test_sync_is_idempotent(db, monkeypatch):
    config = make_config(turris={"services": {"ssh": True}})
    monkeypatch.setattr("banlog.feeds.turris.TurrisFeed.fetch", lambda self, url: b"1.2.3.4,tag\n")
    monkeypatch.setattr("banlog.nft.replace_set", lambda svc, ips: None)

    run_sync(config, db)
    report = run_sync(config, db)

    assert report.results[0].added == 0
    assert report.results[0].removed == 0


def test_sync_fetch_error_skips_feed(db, monkeypatch):
    config = make_config(turris={"services": {"ssh": True}})

    def fail(self, url: str) -> bytes:
        raise ConnectionError("refused")

    monkeypatch.setattr("banlog.feeds.turris.TurrisFeed.fetch", fail)
    monkeypatch.setattr("banlog.nft.replace_set", lambda svc, ips: None)

    report = run_sync(config, db)

    assert report.results[0].status == "fetch_error"
    assert db.execute("SELECT count(*) FROM blocked_ips").fetchone()[0] == 0


def test_sync_closes_orphan_rows(db, monkeypatch):
    now = int(time.time())
    db.execute("INSERT INTO blocked_ips(ip, source, service, start_ts) VALUES (?, ?, ?, ?)",
               ("3.3.3.3", "old_feed", "ssh", now - 200))
    db.commit()
    config = make_config(new_feed={"services": {"ssh": True}})
    monkeypatch.setattr("banlog.feeds.turris.TurrisFeed.fetch", lambda self, url: b"1.2.3.4,tag\n")
    monkeypatch.setattr("banlog.nft.replace_set", lambda svc, ips: None)

    run_sync(config, db)

    assert db.execute(
        "SELECT * FROM blocked_ips WHERE source='old_feed' AND end_ts IS NOT NULL"
    ).fetchone() is not None


def test_sync_multi_feed_nft_set_is_union(db, monkeypatch):
    config = make_config(
        feed_a={"services": {"ssh": True}},
        feed_b={"services": {"ssh": True}},
    )
    responses = {"feed_a": b"1.1.1.1,tag\n", "feed_b": b"2.2.2.2,tag\n"}

    def fake_fetch(self: object, url: str) -> bytes:
        for name, raw in responses.items():
            if name in url:
                return raw
        return b""

    nft_calls: list[tuple] = []
    monkeypatch.setattr("banlog.feeds.turris.TurrisFeed.fetch", fake_fetch)
    monkeypatch.setattr("banlog.nft.replace_set", lambda svc, ips: nft_calls.append((svc, frozenset(ips))))

    run_sync(config, db)

    last_ssh = next(c for c in reversed(nft_calls) if c[0] == "ssh")
    assert last_ssh[1] == frozenset({"1.1.1.1", "2.2.2.2"})
