# banlog - Product Requirements Document

## Overview

`banlog` is a Python CLI tool that maintains nftables sets of blocked IP addresses sourced from external blocklist feeds, with full historical audit trail in SQLite. Primary deployment target is NixOS hosts; the tool itself has no NixOS dependency and runs on any Linux with `nft` available.

**MVP scope:** single feed source (Turris greylist), two protected services (SSH, HTTPS), SQLite history, CLI for inspection. Fail2ban integration, web UI, Prometheus metrics, and multiple feeds are explicitly out of scope but the architecture must accommodate them as future extensions.

## Goals

1. Maintain nftables sets `banlog_ssh` and `banlog_https` populated from enabled feeds.
2. Atomic updates - never leave sets in inconsistent state during refresh.
3. Persistent history in SQLite: every IP's first appearance, last departure, source, and target service.
4. Toggle feeds on/off per service via `lists.json` without code changes.
5. CLI for: sync, status, history queries.
6. Designed for extension: adding a new feed = new feed parser class + entry in `lists.json`.

## Non-goals (MVP)

- Fail2ban integration (architecture must allow it; not implemented)
- Web UI or dashboard
- Prometheus metrics endpoint
- IPv6 (server is IPv4-only)
- Multi-host coordination (each host runs independently)
- Generating `lists.json` from NixOS - manual editing post-deploy is fine for MVP

## Tech stack

- **Language:** Python 3.11+
- **Dep manager:** `uv`
- **Runtime deps:** `requests` only
- **Stdlib:** `sqlite3`, `subprocess`, `argparse`, `logging`, `json`, `csv`, `ipaddress`, `dataclasses`
- **Dev deps:** `pytest`, `pytest-cov`, `ruff`, `mypy`
- **Packaging:** `pyproject.toml` with `[project.scripts]` exposing `banlog` entry point
- **Logging:** stdout only (systemd journal captures it)

## Repository structure

```
banlog/
├── pyproject.toml
├── README.md
├── LICENSE
├── .github/workflows/ci.yml
├── config/
│   └── lists.example.json
├── src/banlog/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── db.py
│   ├── nft.py
│   ├── sync.py
│   ├── utils.py
│   ├── feeds/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── turris.py
│   └── migrations/
│       └── 001_initial.sql
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_db.py
│   │   ├── test_config.py
│   │   ├── test_feeds_turris.py
│   │   ├── test_sync.py
│   │   └── test_nft.py
│   └── integration/
│       └── test_sync_e2e.py
└── scripts/
    └── smoke-test.sh
```

## Configuration: `lists.json`

Single source of truth for which feeds are enabled and for which services. Hand-edited in MVP, located at `/etc/banlog/lists.json` by default (overridable via `--config`).

Schema:

```json
{
  "feeds": {
    "turris_greylist": {
      "type": "turris",
      "url": "https://www.turris.com/greylist-data/greylist-latest.csv",
      "refresh_minutes": 60,
      "services": {
        "ssh": { "enabled": true },
        "https": { "enabled": false }
      }
    }
  }
}
```

Field semantics:

- `feeds.<name>.type` - feed parser implementation key (registry in `feeds/__init__.py`)
- `feeds.<name>.url` - source URL
- `feeds.<name>.refresh_minutes` - hint for systemd timer, not enforced by code
- `feeds.<name>.services.<svc>.enabled` - whether this feed contributes IPs to set `banlog_<svc>`

Supported services in MVP: `ssh`, `https`. Adding a service later = new key, no code change beyond nft module ensuring the set exists.

Config loader (`config.py`) validates manually (file exists, JSON parses, required keys present, types correct). On error: log clear message, exit 2.

## Database

SQLite at `/var/lib/banlog/banlog.db` by default (overridable via `--db`). Single writer (sync process), readers (CLI status/history) coexist via WAL.

**Connection pragmas** (set on every connection open in `db.py`):

```sql
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;
```

`busy_timeout` ensures CLI reads do not crash with `database is locked` when a sync is mid-transaction.

**Schema versioning:**

A dedicated `schema_version` table records the current schema revision. The migrator runs at every connection open:

1. If DB is empty → create all tables at latest version, insert `schema_version` row.
2. If `schema_version` < latest → apply ordered migration scripts.
3. If `schema_version` > latest → refuse to start (downgrade not supported).

```sql
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_ts INTEGER NOT NULL
);
```

Migrations live in `src/banlog/migrations/` as numbered `.sql` files (e.g. `001_initial.sql`). MVP ships with migration 001 only. This avoids painful ad-hoc upgrades later (Fail2ban source, IPv6, etc.).

**Packaging requirement:** SQL files must be installed as package data, otherwise `uv` / `pipx` builds will not ship them into `site-packages`. In `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/banlog"]

[tool.hatch.build.targets.wheel.force-include]
"src/banlog/migrations" = "banlog/migrations"
```

(Build backend is `hatchling` - simpler than setuptools for this case. If the implementer picks setuptools instead, the equivalent is `[tool.setuptools.package-data] "banlog.migrations" = ["*.sql"]`.)

At runtime, migrations are loaded via `importlib.resources.files("banlog.migrations").joinpath(f"{n:03d}_*.sql").read_text()` - no filesystem assumptions, works regardless of install method (editable, wheel, zipapp).

Schema:

```sql
CREATE TABLE blocked_ips (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ip          TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    service     TEXT    NOT NULL,
    start_ts    INTEGER NOT NULL,
    end_ts      INTEGER,
    metadata    TEXT
);

CREATE INDEX idx_active     ON blocked_ips(ip, source, service) WHERE end_ts IS NULL;
CREATE INDEX idx_ip         ON blocked_ips(ip);
CREATE INDEX idx_service    ON blocked_ips(service);
CREATE INDEX idx_start_ts   ON blocked_ips(start_ts);

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
```

Conventions:

- Timestamps are Unix epoch seconds (INTEGER).
- `end_ts IS NULL` means the IP is currently active in that (source, service) combination.
- An IP appearing multiple times over time has multiple rows (one per ban period).
- `metadata` is optional JSON string for source-specific data (e.g. Turris tags).
- `status` in `sync_runs` is one of: `success`, `fetch_error`, `parse_error`, `nft_error`.

## Feeds

Abstract base class `FeedParser` in `feeds/base.py`:

```python
class FeedParser:
    name: str
    def fetch(self, url: str) -> bytes: ...
    def parse(self, raw: bytes) -> set[str]: ...
```

Implementations:

- `feeds/turris.py` - parses Turris greylist CSV format. Returns set of IPv4 addresses as strings. Each candidate entry is validated via `ipaddress.IPv4Address(...)`. IPv6 entries, malformed lines, and any value failing validation are silently dropped (with a per-feed DEBUG-level count logged at end of parse).

Registry in `feeds/__init__.py`:

```python
FEED_REGISTRY: dict[str, type[FeedParser]] = {
    "turris": TurrisFeed,
}
```

Adding a feed in future = new module under `feeds/`, register in `FEED_REGISTRY`.

## nftables integration

Module `nft.py` wraps `subprocess.run(["nft", ...])`.

**Set naming:** `banlog_<service>` (e.g. `banlog_ssh`, `banlog_https`).

**Table:** `inet banlog`. Created and owned by this tool, not the NixOS firewall. The NixOS module (separate work, not part of this repo) will add `drop` rules referencing these sets.

**Operations:**

- `ensure_table_and_sets(services: list[str])` - idempotently create table `inet banlog` and sets `banlog_<svc>` for each service
- `replace_set(service: str, ips: set[str])` - atomic replace via `nft -f <tempfile>`

**Atomic replace - flush + add in one transaction:**

A single `nft -f` invocation applies its entire ruleset as one kernel transaction. `flush` followed by `add element` in the same file is therefore atomic from the perspective of any rule referencing the set - the kernel never sees an empty intermediate state, packet matching against the set transitions from old contents to new contents in one step.

The earlier proposal of a rename-swap pattern was reconsidered: `rename set` can fail when the set is actively referenced by a `drop` rule, which is exactly the production state. `flush + add` is the simpler, safer, natively-atomic option.

To avoid argv/stdin size pressure with large feeds (tens of thousands of IPs), the ruleset is written to a temp file (`tempfile.NamedTemporaryFile` in `/tmp`, mode `w`, suffix `.nft`) and loaded via `nft -f <path>`. Temp file is removed in a `finally` block regardless of outcome.

Ruleset template:

```
flush set inet banlog banlog_ssh
add element inet banlog banlog_ssh { 1.1.1.1, 2.2.2.2 }
```

For empty input, only the `flush` line is emitted.

**Note on `flags interval`:** the set is created in `ensure_table_and_sets` with `flags interval` to allow future CIDR-range entries (some feeds publish ranges). For MVP all entries are /32 host addresses, but having the flag in place avoids a future destructive set recreation.

**Error handling:** any non-zero exit from `nft` raises `NftError` with stderr captured. Caller logs and updates `sync_runs.status = "nft_error"`.

## Sync logic

Module `sync.py` exposes `run_sync(config, db) -> SyncReport`.

**Order of operations for a single sync run:**

1. **Open run record:** insert `sync_runs` row with `status='running'`, `started_ts=now`. One row per feed processed (so a multi-feed sync produces multiple `sync_runs` rows).
2. **Cleanup orphan rows from disabled/removed configs** (runs once at start, before any feed processing):
   - Query DB for all distinct `(source, service)` pairs with active rows (`end_ts IS NULL`).
   - For each pair not present in the currently-enabled config, set `end_ts = now` for all its active rows.
   - This entire cleanup happens in **one DB transaction**. If it fails, sync aborts before touching any nftables set, preventing DB/firewall divergence.
3. **For each enabled feed** in config:
   a. Fetch feed via its parser. On fetch error: log, set `sync_runs.status='fetch_error'`, continue with next feed (DB and nft set for this feed untouched).
   b. Parse to `set[str]` of current IPs (with `parse_ip` validation; invalid entries dropped + counted).
   c. For each service where this feed is enabled:
      - Query DB for currently active IPs for `(source=feed_name, service=svc)`.
      - Compute `added = new - active`, `removed = active - new`.
      - In a single DB transaction:
        - `UPDATE blocked_ips SET end_ts=? ... ` for each removed IP
        - `INSERT INTO blocked_ips ... ` for each added IP
4. **Rebuild nftables sets** (after all DB writes succeed):
   - For each service present in any enabled feed: query the union of currently-active IPs across all enabled `(source, service)` rows targeting that service, then call `nft.replace_set(service, ips)`.
   - On nft error: log, set the affected `sync_runs.status='nft_error'`. DB state is already consistent; firewall set will be retried on next sync.
5. **Close run records:** update each `sync_runs` row with `finished_ts`, `added`, `removed`, `total`, final `status`.

**Transactional guarantees:**

- Step 2 (cleanup) is atomic. Either all orphans are closed or none are.
- Step 3c (per-feed-per-service diff application) is atomic per pair.
- Step 4 (nft rebuild) is best-effort and idempotent: failure here does not corrupt DB; next successful sync will reconstruct the set from current DB state.
- These guarantees mean **DB is always source of truth**; nft sets are a derived projection. A drift (e.g. someone manually `nft flush set`) self-heals on next sync.

**Multi-feed unions:** when multiple feeds target the same service, the nft set is the union of all active IPs across feeds. Each feed maintains its own DB rows (different `source` value), so toggling one feed off does not affect another feed's contributions.

Notes:

- All IP strings entering DB or nft pass `utils.parse_ip` validation. Invalid entries from a feed are skipped with a WARNING log. The same validation applies to any CLI argument accepting an IP (`history --ip`, future `ban --ip`).

## CLI

Entry point: `banlog` (via `[project.scripts]`).

Global flags:
- `--config PATH` (default `/etc/banlog/lists.json`)
- `--db PATH` (default `/var/lib/banlog/banlog.db`)
- `--log-level LEVEL` (default `INFO`)

Subcommands:

- `banlog sync`
  Runs full sync of all enabled feeds. Updates DB and nft sets. Exit 0 on full success, 1 if any feed failed, 2 on config/setup error.

- `banlog status`
  Prints summary table: per (source, service) → active count, last sync time, last sync status.

- `banlog history --ip IP`
  Prints all rows in `blocked_ips` for given IP, ordered by `start_ts`.

- `banlog list --service SVC [--source SRC] [--active|--all]`
  Lists IPs. Default `--active`.

- `banlog feeds`
  Lists configured feeds and their enabled/disabled state per service.

Output is plain text aligned columns by default. No JSON output in MVP (can add `--json` later).

## Input validation

A shared helper `utils.parse_ip(value: str) -> str` wraps `ipaddress.IPv4Address` and:

- Raises `ValueError` (caught by CLI → exit 2 with clear message) on invalid input.
- Returns normalized canonical form (e.g. `"01.02.03.04"` → `"1.2.3.4"`).

This helper is used by:

- Feed parsers when ingesting raw lines (invalid → skip + log).
- CLI commands accepting `--ip` arguments (invalid → exit 2 + message).
- Any future `ban`/`unban` commands.

Even though SQL queries use parameter binding (no injection risk), validation provides defense-in-depth and prevents garbage entries from polluting DB or causing cryptic `nft` errors downstream.

## Testing

### Unit tests (`tests/unit/`)

Must run without root and without `nft` binary. Use:
- `pytest` with `tmp_path` fixture for filesystem
- in-memory SQLite (`:memory:`) for DB tests
- `requests-mock` or simple monkeypatching for HTTP
- `subprocess` calls mocked at boundary

Coverage targets:
- `test_db.py` - schema creation, schema versioning (fresh DB, already-current DB, future-version refusal), insert active IP, close IP, query active, query history
- `test_config.py` - load valid config, reject malformed, reject unknown feed type
- `test_feeds_turris.py` - parse known good CSV, handle empty, handle IPv6 entries, handle malformed lines, ensure IP validation drops garbage
- `test_sync.py` - diff logic (added/removed computation), multi-feed union per service, fetch error handling, **disabled-feed cleanup** (active rows for a (source, service) that was toggled off get `end_ts` set)
- `test_nft.py` - command construction with rename-swap pattern (mocked subprocess), error propagation, temp file cleanup on both success and failure paths
- `test_utils.py` - `parse_ip` accepts valid, rejects invalid, canonicalizes

### Integration tests (`tests/integration/`)

Marked `@pytest.mark.integration`, skipped by default. Run with `pytest -m integration`.

- `test_sync_e2e.py` - full sync against a local HTTP server serving fixture CSV, real SQLite file, real `nft` calls against a **test table prefix** (`banlog_test`) so production state is untouched. Test cleans up its table at teardown.

Requires `nft` available on test host. CI runs in container with nftables installed.

### Smoke test (`scripts/smoke-test.sh`)

Shell script runnable on production host post-deploy:
1. `banlog status` exits 0
2. `nft list set inet banlog banlog_ssh` exists
3. `banlog history --ip 8.8.8.8` exits 0 (empty result is fine)
4. Latest `sync_runs` row has `status='success'`

## CI

`.github/workflows/ci.yml`:

- Job `lint`: `ruff check`, `ruff format --check`, `mypy src/`
- Job `test-unit`: `pytest tests/unit/ --cov=banlog --cov-report=term-missing` (fail if coverage < 80%)
- Job `test-integration`: container with `nftables` package, run `pytest -m integration`

## Future extensions (out of MVP, but architecture must support)

1. **More feeds** - add parser class, register in `FEED_REGISTRY`, add entry in `lists.json`. No core changes.
2. **Fail2ban integration** - new "source" value `fail2ban` written by external action hook calling `banlog ban --source fail2ban --ip X --service ssh`. CLI subcommands `ban`/`unban` to be added later; DB schema already supports it.
3. **Prometheus metrics** - new `metrics.py` module reading `sync_runs` and active counts, exposed via simple HTTP endpoint or textfile collector.
4. **Web UI** - read-only Flask/FastAPI app over the SQLite DB.
5. **NixOS-generated `lists.json`** - NixOS module renders JSON from typed options instead of hand-editing.
6. **IPv6** - add `banlog_ssh_v6` etc., separate logic path or merged via dual-stack sets.

## Acceptance criteria

MVP is done when:

1. `uv sync` installs dev environment cleanly.
2. `pytest tests/unit/` passes with ≥80% coverage.
3. `pytest -m integration` passes in a container with `nftables`.
4. Running `banlog sync` against real Turris feed:
   - Populates `banlog_ssh` (or `banlog_https`, per config) with the feed IPs
   - DB has matching active rows
   - Second run with unchanged feed produces zero diffs (idempotent)
   - Running with a feed that has fewer IPs closes the missing rows with `end_ts`
   - Toggling a feed from `enabled: true` to `enabled: false` in `lists.json` and re-running sync closes all its active rows and removes its contribution from the nft set
5. `banlog status`, `history`, `list`, `feeds` produce sensible output.
6. `nft list ruleset` shows table `inet banlog` with the expected sets, populated via rename-swap (verifiable by observing set is never empty between two successive syncs with non-empty feed).
7. Schema versioning works: fresh DB initializes to version 1; tampering version to a higher value causes startup refusal with clear error.
8. `banlog history --ip not_an_ip` exits with code 2 and a clear validation message.
9. README has install + usage instructions including the manual `nft` rule example for blocking traffic.

## Deliverables

- Working Python project at `github:<user>/banlog`
- `pyproject.toml` with `uv` lockfile
- All tests passing locally
- GitHub Actions CI green
- README with: install (via `uv` and via `pipx`), config example, CLI reference, example `nft` rules to wire the sets into actual firewall, troubleshooting
- `config/lists.example.json` ready to copy to `/etc/banlog/lists.json`
