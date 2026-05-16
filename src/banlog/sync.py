import logging
import time
from dataclasses import dataclass, field
from sqlite3 import Connection

from banlog import nft
from banlog.config import Config, FeedConfig
from banlog.feeds import FEED_REGISTRY

log = logging.getLogger(__name__)


@dataclass
class FeedSyncResult:
    source: str
    status: str
    added: int = 0
    removed: int = 0
    total: int = 0
    error: str | None = None


@dataclass
class SyncReport:
    results: list[FeedSyncResult] = field(default_factory=list)


def run_sync(config: Config, db: Connection) -> SyncReport:
    report = SyncReport()
    now = int(time.time())
    _close_orphans(config, db, now)
    for feed_name, feed_cfg in config.feeds.items():
        enabled = [svc for svc, cfg in feed_cfg.services.items() if cfg.enabled]
        if enabled:
            _process_feed(feed_name, feed_cfg, enabled, db, now, report)
    _rebuild_sets(config, db, report)
    return report


def _close_orphans(config: Config, db: Connection, now: int) -> None:
    active = db.execute(
        "SELECT DISTINCT source, service FROM blocked_ips WHERE end_ts IS NULL"
    ).fetchall()
    enabled: set[tuple[str, str]] = {
        (feed, svc)
        for feed, fc in config.feeds.items()
        for svc, sc in fc.services.items()
        if sc.enabled
    }
    orphans = [
        (r["source"], r["service"]) for r in active if (r["source"], r["service"]) not in enabled
    ]
    if not orphans:
        return
    with db:
        for source, service in orphans:
            db.execute(
                "UPDATE blocked_ips SET end_ts=? WHERE source=? AND service=? AND end_ts IS NULL",
                (now, source, service),
            )
    log.info("Closed orphan rows for %d (source, service) pairs", len(orphans))


def _process_feed(
    feed_name: str,
    feed_cfg: FeedConfig,
    enabled_services: list[str],
    db: Connection,
    now: int,
    report: SyncReport,
) -> None:
    run_id = db.execute(
        "INSERT INTO sync_runs(source, started_ts, status) VALUES (?,?,'running')",
        (feed_name, now),
    ).lastrowid
    db.commit()

    parser = FEED_REGISTRY[feed_cfg.type]()
    try:
        raw = parser.fetch(feed_cfg.url)
    except Exception as e:
        log.error("Fetch error '%s': %s", feed_name, e)
        db.execute(
            "UPDATE sync_runs SET finished_ts=?,status='fetch_error',error=? WHERE id=?",
            (now, str(e), run_id),
        )
        db.commit()
        report.results.append(FeedSyncResult(source=feed_name, status="fetch_error", error=str(e)))
        return

    try:
        new_ips = parser.parse(raw)
    except Exception as e:
        log.error("Parse error '%s': %s", feed_name, e)
        db.execute(
            "UPDATE sync_runs SET finished_ts=?,status='parse_error',error=? WHERE id=?",
            (now, str(e), run_id),
        )
        db.commit()
        report.results.append(FeedSyncResult(source=feed_name, status="parse_error", error=str(e)))
        return

    total_added = total_removed = 0
    for svc in enabled_services:
        active_ips = {
            r["ip"]
            for r in db.execute(
                "SELECT ip FROM blocked_ips WHERE source=? AND service=? AND end_ts IS NULL",
                (feed_name, svc),
            )
        }
        added, removed = new_ips - active_ips, active_ips - new_ips
        total_added += len(added)
        total_removed += len(removed)
        with db:
            for ip in removed:
                db.execute(
                    "UPDATE blocked_ips SET end_ts=?"
                    " WHERE ip=? AND source=? AND service=? AND end_ts IS NULL",
                    (now, ip, feed_name, svc),
                )
            for ip in added:
                db.execute(
                    "INSERT INTO blocked_ips(ip, source, service, start_ts) VALUES (?,?,?,?)",
                    (ip, feed_name, svc, now),
                )

    db.execute(
        "UPDATE sync_runs SET finished_ts=?,status='success',added=?,removed=?,total=? WHERE id=?",
        (now, total_added, total_removed, len(new_ips), run_id),
    )
    db.commit()
    report.results.append(
        FeedSyncResult(
            source=feed_name,
            status="success",
            added=total_added,
            removed=total_removed,
            total=len(new_ips),
        )
    )
    log.info("Feed '%s': +%d -%d total=%d", feed_name, total_added, total_removed, len(new_ips))


def _rebuild_sets(config: Config, db: Connection, report: SyncReport) -> None:
    services = {
        svc for fc in config.feeds.values() for svc, sc in fc.services.items() if sc.enabled
    }
    for svc in sorted(services):
        ips = {
            r["ip"]
            for r in db.execute(
                "SELECT DISTINCT ip FROM blocked_ips WHERE service=? AND end_ts IS NULL", (svc,)
            )
        }
        try:
            nft.replace_set(svc, ips)
            log.info("Updated banlog_%s: %d IPs", svc, len(ips))
        except nft.NftError as e:
            log.error("nft error banlog_%s: %s", svc, e)
            for r in report.results:
                if r.status == "success" and r.source in config.feeds:
                    fc = config.feeds[r.source]
                    if svc in fc.services and fc.services[svc].enabled:
                        r.status = "nft_error"
