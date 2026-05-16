import argparse
import logging
import sys

from banlog.config import load_config
from banlog.db import open_db
from banlog import nft, sync
from banlog.utils import parse_ip

DEFAULT_CONFIG = "/etc/banlog/lists.json"
DEFAULT_DB = "/var/lib/banlog/banlog.db"


def cmd_sync(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    db = open_db(args.db)
    services = list({
        svc for fc in config.feeds.values()
        for svc, sc in fc.services.items() if sc.enabled
    })
    try:
        nft.ensure_table_and_sets(services)
    except nft.NftError as e:
        logging.error("Failed to ensure nft table/sets: %s", e)
        return 2
    report = sync.run_sync(config, db)
    return 1 if any(r.status != "success" for r in report.results) else 0


def cmd_status(args: argparse.Namespace) -> int:
    db = open_db(args.db)
    rows = db.execute("""
        SELECT b.source, b.service, COUNT(*) AS active_count,
               sr.finished_ts, sr.status AS last_status
        FROM blocked_ips b
        LEFT JOIN sync_runs sr ON sr.source = b.source
            AND sr.id = (SELECT MAX(id) FROM sync_runs WHERE source = b.source)
        WHERE b.end_ts IS NULL
        GROUP BY b.source, b.service
    """).fetchall()
    if not rows:
        print("No active blocked IPs.")
        return 0
    print(f"{'SOURCE':<30} {'SERVICE':<10} {'ACTIVE':>8}  {'LAST SYNC':<12}  STATUS")
    print("-" * 72)
    for row in rows:
        last = str(row["finished_ts"]) if row["finished_ts"] else "never"
        print(f"{row['source']:<30} {row['service']:<10} {row['active_count']:>8}  {last:<12}  {row['last_status'] or '-'}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    try:
        ip = parse_ip(args.ip)
    except ValueError:
        logging.error("Invalid IP address: %s", args.ip)
        return 2
    db = open_db(args.db)
    rows = db.execute(
        "SELECT * FROM blocked_ips WHERE ip=? ORDER BY start_ts", (ip,)
    ).fetchall()
    if not rows:
        print(f"No history for {ip}")
        return 0
    print(f"{'ID':>6}  {'SOURCE':<22}  {'SERVICE':<10}  {'START':>12}  {'END':>12}  METADATA")
    print("-" * 80)
    for row in rows:
        end = str(row["end_ts"]) if row["end_ts"] else "active"
        print(f"{row['id']:>6}  {row['source']:<22}  {row['service']:<10}  {row['start_ts']:>12}  {end:>12}  {row['metadata'] or ''}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    db = open_db(args.db)
    query = "SELECT ip, source, service, start_ts, end_ts FROM blocked_ips WHERE service=?"
    params: list[str] = [args.service]
    if args.source:
        query += " AND source=?"
        params.append(args.source)
    if not args.all:
        query += " AND end_ts IS NULL"
    query += " ORDER BY start_ts"
    for row in db.execute(query, params):
        end = str(row["end_ts"]) if row["end_ts"] else "active"
        print(f"{row['ip']:<18}  {row['source']:<22}  {row['service']:<10}  {row['start_ts']}  {end}")
    return 0


def cmd_feeds(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(f"{'FEED':<30}  {'TYPE':<12}  {'SERVICE':<10}  ENABLED")
    print("-" * 62)
    for name, fc in config.feeds.items():
        for svc, sc in fc.services.items():
            print(f"{name:<30}  {fc.type:<12}  {svc:<10}  {sc.enabled}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="banlog")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--log-level", default="INFO")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync")
    sub.add_parser("status")

    hist = sub.add_parser("history")
    hist.add_argument("--ip", required=True)

    lst = sub.add_parser("list")
    lst.add_argument("--service", required=True)
    lst.add_argument("--source")
    grp = lst.add_mutually_exclusive_group()
    grp.add_argument("--active", dest="all", action="store_false")
    grp.add_argument("--all", dest="all", action="store_true")
    lst.set_defaults(all=False)

    sub.add_parser("feeds")

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(levelname)s %(message)s")

    handlers = {
        "sync": cmd_sync,
        "status": cmd_status,
        "history": cmd_history,
        "list": cmd_list,
        "feeds": cmd_feeds,
    }
    sys.exit(handlers[args.command](args))
