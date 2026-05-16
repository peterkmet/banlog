# banlog MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `banlog`, a Python CLI tool that maintains nftables IP blocklist sets from external feeds with a SQLite audit trail.

**Architecture:** Feed parsers fetch and parse IPs from remote sources; the sync engine diffs against DB state and atomically updates nftables sets via `nft -f <tempfile>`; DB is always source of truth — nft sets are a derived projection that self-heals on next sync.

**Tech Stack:** Python 3.11+, uv, hatchling, sqlite3, requests, subprocess/nft, pytest, ruff, mypy

---

## File Map

**Created:**
- `pyproject.toml`
- `src/banlog/__init__.py`
- `src/banlog/__main__.py`
- `src/banlog/utils.py`
- `src/banlog/db.py`
- `src/banlog/config.py`
- `src/banlog/nft.py`
- `src/banlog/sync.py`
- `src/banlog/cli.py`
- `src/banlog/feeds/__init__.py`
- `src/banlog/feeds/base.py`
- `src/banlog/feeds/turris.py`
- `src/banlog/migrations/__init__.py`
- `src/banlog/migrations/001_initial.sql`
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/unit/__init__.py`
- `tests/unit/test_utils.py`
- `tests/unit/test_db.py`
- `tests/unit/test_config.py`
- `tests/unit/test_feeds_turris.py`
- `tests/unit/test_nft.py`
- `tests/unit/test_sync.py`
- `tests/integration/__init__.py`
- `tests/integration/test_sync_e2e.py`
- `.github/workflows/ci.yml`
- `config/lists.example.json`
- `scripts/smoke-test.sh`
- `README.md`

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/banlog/__init__.py`
- Create: `src/banlog/__main__.py`
- Create: `src/banlog/migrations/__init__.py`
- Create: `src/banlog/feeds/__init__.py` (stub)
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/banlog/feeds src/banlog/migrations tests/unit tests/integration config scripts .github/workflows
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[project]
name = "banlog"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["requests>=2.31.0"]

[project.scripts]
banlog = "banlog.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/banlog"]

[tool.hatch.build.targets.wheel.force-include]
"src/banlog/migrations" = "banlog/migrations"

[dependency-groups]
dev = [
    "pytest>=7.4",
    "pytest-cov>=4.0",
    "requests-mock>=1.11",
    "ruff>=0.4",
    "mypy>=1.10",
    "types-requests>=2.31",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: requires nft binary and root"]

[tool.ruff]
src = ["src"]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.mypy]
python_version = "3.11"
strict = true
```

- [ ] **Step 3: Write stub files**

`src/banlog/__init__.py` — empty file

`src/banlog/__main__.py`:
```python
from banlog.cli import main

main()
```

`src/banlog/migrations/__init__.py` — empty file

`src/banlog/feeds/__init__.py` (stub, replaced in Task 4):
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from banlog.feeds.base import FeedParser

FEED_REGISTRY: dict[str, type["FeedParser"]] = {}
```

`tests/__init__.py` — empty
`tests/unit/__init__.py` — empty
`tests/integration/__init__.py` — empty

- [ ] **Step 4: Install and verify**

```bash
uv sync
uv run python -c "import banlog; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Init git and commit**

```bash
git init
git add .
git commit -m "chore: project scaffold"
```

---

## Task 2: utils module

**Files:**
- Create: `src/banlog/utils.py`
- Create: `tests/unit/test_utils.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_utils.py`:
```python
import pytest
from banlog.utils import parse_ip


def test_valid_ip():
    assert parse_ip("1.2.3.4") == "1.2.3.4"


def test_normalizes_leading_zeros():
    assert parse_ip("01.02.03.04") == "1.2.3.4"


def test_rejects_invalid_string():
    with pytest.raises(ValueError):
        parse_ip("not_an_ip")


def test_rejects_ipv6():
    with pytest.raises(ValueError):
        parse_ip("::1")


def test_rejects_out_of_range():
    with pytest.raises(ValueError):
        parse_ip("999.0.0.1")


def test_rejects_empty():
    with pytest.raises(ValueError):
        parse_ip("")
```

- [ ] **Step 2: Run tests, verify ERRORS**

```bash
uv run pytest tests/unit/test_utils.py -v
```

Expected: ImportError (module doesn't exist)

- [ ] **Step 3: Implement**

`src/banlog/utils.py`:
```python
import ipaddress


def parse_ip(value: str) -> str:
    return str(ipaddress.IPv4Address(value))
```

- [ ] **Step 4: Run tests, verify 6 passed**

```bash
uv run pytest tests/unit/test_utils.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/banlog/utils.py tests/unit/test_utils.py
git commit -m "feat: add parse_ip utility"
```

---

## Task 3: Database — migrations + db module

**Files:**
- Create: `src/banlog/migrations/001_initial.sql`
- Create: `src/banlog/db.py`
- Create: `tests/unit/test_db.py`

- [ ] **Step 1: Write migration SQL**

`src/banlog/migrations/001_initial.sql`:
```sql
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
```

- [ ] **Step 2: Write failing tests**

`tests/unit/test_db.py`:
```python
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
```

- [ ] **Step 3: Run tests, verify ERRORS**

```bash
uv run pytest tests/unit/test_db.py -v
```

- [ ] **Step 4: Implement db.py**

`src/banlog/db.py`:
```python
import importlib.resources
import sqlite3


LATEST_VERSION = 1


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")


def _get_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0


def _load_migration(n: int) -> str:
    pkg = importlib.resources.files("banlog.migrations")
    for res in pkg.iterdir():
        if res.name.startswith(f"{n:03d}_"):
            return res.read_text()
    raise FileNotFoundError(f"Migration {n:03d} not found")


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    version = _get_version(conn)
    if version > LATEST_VERSION:
        conn.close()
        raise RuntimeError(
            f"DB schema version {version} > code version {LATEST_VERSION}; downgrade not supported"
        )
    for n in range(version + 1, LATEST_VERSION + 1):
        conn.executescript(_load_migration(n))
    return conn
```

- [ ] **Step 5: Run tests, verify 7 passed**

```bash
uv run pytest tests/unit/test_db.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/banlog/db.py src/banlog/migrations/ tests/unit/test_db.py
git commit -m "feat: add db module with schema migrations"
```

---

## Task 4: Feed parsers

**Files:**
- Create: `src/banlog/feeds/base.py`
- Create: `src/banlog/feeds/turris.py`
- Modify: `src/banlog/feeds/__init__.py`
- Create: `tests/unit/test_feeds_turris.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_feeds_turris.py`:
```python
import pytest
from banlog.feeds.turris import TurrisFeed

VALID_CSV = b"# comment\n1.2.3.4,some_tag\n5.6.7.8,other_tag\n10.0.0.1,tag3\n"
IPV6_CSV = b"1.2.3.4,tag\n::1,ipv6\n2001:db8::1,ipv6\n"
MALFORMED_CSV = b"1.2.3.4,tag\nnot_an_ip,tag\n999.999.999.999,tag\n5.6.7.8,tag\n"


def test_parse_valid_csv():
    assert TurrisFeed().parse(VALID_CSV) == {"1.2.3.4", "5.6.7.8", "10.0.0.1"}


def test_parse_empty():
    assert TurrisFeed().parse(b"") == set()


def test_parse_comments_only():
    assert TurrisFeed().parse(b"# comment\n") == set()


def test_parse_drops_ipv6():
    result = TurrisFeed().parse(IPV6_CSV)
    assert "::1" not in result
    assert "2001:db8::1" not in result
    assert "1.2.3.4" in result


def test_parse_drops_malformed():
    result = TurrisFeed().parse(MALFORMED_CSV)
    assert "not_an_ip" not in result
    assert "999.999.999.999" not in result
    assert {"1.2.3.4", "5.6.7.8"}.issubset(result)


def test_fetch_makes_http_request(requests_mock):
    requests_mock.get("http://example.com/feed.csv", content=VALID_CSV)
    assert TurrisFeed().fetch("http://example.com/feed.csv") == VALID_CSV


def test_registry_contains_turris():
    from banlog.feeds import FEED_REGISTRY
    assert "turris" in FEED_REGISTRY
```

- [ ] **Step 2: Run tests, verify ERRORS**

```bash
uv run pytest tests/unit/test_feeds_turris.py -v
```

- [ ] **Step 3: Implement feeds/base.py**

`src/banlog/feeds/base.py`:
```python
from abc import ABC, abstractmethod


class FeedParser(ABC):
    name: str

    @abstractmethod
    def fetch(self, url: str) -> bytes: ...

    @abstractmethod
    def parse(self, raw: bytes) -> set[str]: ...
```

- [ ] **Step 4: Implement feeds/turris.py**

`src/banlog/feeds/turris.py`:
```python
import csv
import io
import logging

import requests

from banlog.feeds.base import FeedParser
from banlog.utils import parse_ip

log = logging.getLogger(__name__)


class TurrisFeed(FeedParser):
    name = "turris"

    def fetch(self, url: str) -> bytes:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.content

    def parse(self, raw: bytes) -> set[str]:
        ips: set[str] = set()
        dropped = 0
        reader = csv.reader(io.StringIO(raw.decode("utf-8", errors="replace")))
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            try:
                ips.add(parse_ip(row[0].strip()))
            except ValueError:
                dropped += 1
        if dropped:
            log.debug("Turris: dropped %d invalid/IPv6 entries", dropped)
        return ips
```

- [ ] **Step 5: Replace feeds/__init__.py**

`src/banlog/feeds/__init__.py`:
```python
from banlog.feeds.base import FeedParser
from banlog.feeds.turris import TurrisFeed

FEED_REGISTRY: dict[str, type[FeedParser]] = {
    "turris": TurrisFeed,
}
```

- [ ] **Step 6: Run tests, verify 7 passed**

```bash
uv run pytest tests/unit/test_feeds_turris.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/banlog/feeds/ tests/unit/test_feeds_turris.py
git commit -m "feat: add feed parsers and Turris implementation"
```

---

## Task 5: Config module

**Files:**
- Create: `src/banlog/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_config.py`:
```python
import json
import pytest
from banlog.config import load_config


def test_load_valid_config(tmp_path):
    cfg = {
        "feeds": {
            "turris_greylist": {
                "type": "turris",
                "url": "http://example.com/feed.csv",
                "refresh_minutes": 60,
                "services": {
                    "ssh": {"enabled": True},
                    "https": {"enabled": False},
                },
            }
        }
    }
    p = tmp_path / "lists.json"
    p.write_text(json.dumps(cfg))
    config = load_config(str(p))
    feed = config.feeds["turris_greylist"]
    assert feed.type == "turris"
    assert feed.services["ssh"].enabled is True
    assert feed.services["https"].enabled is False


def test_missing_file_exits_2(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load_config(str(tmp_path / "missing.json"))
    assert exc.value.code == 2


def test_invalid_json_exits_2(tmp_path):
    p = tmp_path / "lists.json"
    p.write_text("not json {{{")
    with pytest.raises(SystemExit) as exc:
        load_config(str(p))
    assert exc.value.code == 2


def test_missing_feeds_key_exits_2(tmp_path):
    p = tmp_path / "lists.json"
    p.write_text(json.dumps({"other": {}}))
    with pytest.raises(SystemExit) as exc:
        load_config(str(p))
    assert exc.value.code == 2


def test_unknown_feed_type_exits_2(tmp_path):
    cfg = {
        "feeds": {
            "myfeed": {
                "type": "does_not_exist",
                "url": "http://example.com",
                "refresh_minutes": 60,
                "services": {"ssh": {"enabled": True}},
            }
        }
    }
    p = tmp_path / "lists.json"
    p.write_text(json.dumps(cfg))
    with pytest.raises(SystemExit) as exc:
        load_config(str(p))
    assert exc.value.code == 2


def test_missing_required_feed_key_exits_2(tmp_path):
    cfg = {"feeds": {"myfeed": {"type": "turris", "url": "http://x.com"}}}
    p = tmp_path / "lists.json"
    p.write_text(json.dumps(cfg))
    with pytest.raises(SystemExit) as exc:
        load_config(str(p))
    assert exc.value.code == 2
```

- [ ] **Step 2: Run tests, verify ERRORS**

```bash
uv run pytest tests/unit/test_config.py -v
```

- [ ] **Step 3: Implement config.py**

`src/banlog/config.py`:
```python
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from banlog.feeds import FEED_REGISTRY

log = logging.getLogger(__name__)


@dataclass
class ServiceConfig:
    enabled: bool


@dataclass
class FeedConfig:
    name: str
    type: str
    url: str
    refresh_minutes: int
    services: dict[str, ServiceConfig]


@dataclass
class Config:
    feeds: dict[str, FeedConfig]


def load_config(path: str) -> Config:
    p = Path(path)
    if not p.exists():
        log.error("Config file not found: %s", path)
        sys.exit(2)
    try:
        data: Any = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        log.error("Config JSON parse error: %s", e)
        sys.exit(2)
    return _parse(data)


def _parse(data: Any) -> Config:
    if not isinstance(data, dict) or "feeds" not in data:
        log.error("Config missing top-level 'feeds' key")
        sys.exit(2)
    feeds: dict[str, FeedConfig] = {}
    for name, raw in data["feeds"].items():
        for key in ("type", "url", "refresh_minutes", "services"):
            if key not in raw:
                log.error("Feed '%s' missing required key '%s'", name, key)
                sys.exit(2)
        if raw["type"] not in FEED_REGISTRY:
            log.error("Unknown feed type '%s' in feed '%s'", raw["type"], name)
            sys.exit(2)
        services: dict[str, ServiceConfig] = {}
        for svc, svc_raw in raw["services"].items():
            if "enabled" not in svc_raw or not isinstance(svc_raw["enabled"], bool):
                log.error("Feed '%s' service '%s' missing boolean 'enabled'", name, svc)
                sys.exit(2)
            services[svc] = ServiceConfig(enabled=svc_raw["enabled"])
        feeds[name] = FeedConfig(
            name=name,
            type=raw["type"],
            url=raw["url"],
            refresh_minutes=raw["refresh_minutes"],
            services=services,
        )
    return Config(feeds=feeds)
```

- [ ] **Step 4: Run tests, verify 6 passed**

```bash
uv run pytest tests/unit/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/banlog/config.py tests/unit/test_config.py
git commit -m "feat: add config loader with validation"
```

---

## Task 6: nft module

**Files:**
- Create: `src/banlog/nft.py`
- Create: `tests/unit/test_nft.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_nft.py`:
```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from banlog.nft import ensure_table_and_sets, replace_set, NftError


def _mock_nft(monkeypatch, returncode: int = 0, stderr: str = "") -> list:
    calls: list = []

    def fake_run(cmd: list, **kwargs: object) -> MagicMock:
        if len(cmd) > 2 and cmd[1] == "-f":
            calls.append((cmd, Path(cmd[2]).read_text()))
        else:
            calls.append((cmd, None))
        m = MagicMock()
        m.returncode = returncode
        m.stderr = stderr
        return m

    monkeypatch.setattr("subprocess.run", fake_run)
    return calls


def test_replace_set_flushes_and_adds_elements(monkeypatch):
    calls = _mock_nft(monkeypatch)
    replace_set("ssh", {"1.2.3.4", "5.6.7.8"})
    content = calls[0][1]
    assert "flush set inet banlog banlog_ssh" in content
    assert "1.2.3.4" in content
    assert "5.6.7.8" in content


def test_replace_set_empty_only_flushes(monkeypatch):
    calls = _mock_nft(monkeypatch)
    replace_set("ssh", set())
    content = calls[0][1]
    assert "flush set inet banlog banlog_ssh" in content
    assert "add element" not in content


def test_replace_set_raises_nft_error(monkeypatch):
    _mock_nft(monkeypatch, returncode=1, stderr="Error: No such table")
    with pytest.raises(NftError, match="No such table"):
        replace_set("ssh", {"1.2.3.4"})


def test_ensure_table_and_sets_both_services(monkeypatch):
    calls = _mock_nft(monkeypatch)
    ensure_table_and_sets(["ssh", "https"])
    content = calls[0][1]
    assert "add table inet banlog" in content
    assert "banlog_ssh" in content
    assert "banlog_https" in content
    assert "flags interval" in content


def test_tempfile_cleaned_up_on_success(monkeypatch):
    paths: list[str] = []

    def fake_run(cmd: list, **kwargs: object) -> MagicMock:
        if len(cmd) > 2 and cmd[1] == "-f":
            paths.append(cmd[2])
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        return m

    monkeypatch.setattr("subprocess.run", fake_run)
    replace_set("ssh", {"1.2.3.4"})
    assert len(paths) == 1
    assert not Path(paths[0]).exists()


def test_tempfile_cleaned_up_on_error(monkeypatch):
    paths: list[str] = []

    def fake_run(cmd: list, **kwargs: object) -> MagicMock:
        if len(cmd) > 2 and cmd[1] == "-f":
            paths.append(cmd[2])
        m = MagicMock()
        m.returncode = 1
        m.stderr = "error"
        return m

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(NftError):
        replace_set("ssh", {"1.2.3.4"})
    assert len(paths) == 1
    assert not Path(paths[0]).exists()
```

- [ ] **Step 2: Run tests, verify ERRORS**

```bash
uv run pytest tests/unit/test_nft.py -v
```

- [ ] **Step 3: Implement nft.py**

`src/banlog/nft.py`:
```python
import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

TABLE = "inet banlog"


class NftError(Exception):
    pass


def _run_nft(args: list[str]) -> None:
    result = subprocess.run(["nft"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        raise NftError(result.stderr.strip())


def _write_and_run(lines: list[str]) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nft", delete=False) as f:
        f.write("\n".join(lines) + "\n")
        path = f.name
    try:
        _run_nft(["-f", path])
    finally:
        Path(path).unlink(missing_ok=True)


def ensure_table_and_sets(services: list[str]) -> None:
    lines = [f"add table {TABLE}"]
    for svc in services:
        lines.append(f"add set {TABLE} banlog_{svc} {{ type ipv4_addr; flags interval; }}")
    _write_and_run(lines)


def replace_set(service: str, ips: set[str]) -> None:
    lines = [f"flush set {TABLE} banlog_{service}"]
    if ips:
        lines.append(f"add element {TABLE} banlog_{service} {{ {', '.join(sorted(ips))} }}")
    _write_and_run(lines)
```

- [ ] **Step 4: Run tests, verify 6 passed**

```bash
uv run pytest tests/unit/test_nft.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/banlog/nft.py tests/unit/test_nft.py
git commit -m "feat: add nft module with atomic set replacement"
```

---

## Task 7: Sync logic

**Files:**
- Create: `src/banlog/sync.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_sync.py`

- [ ] **Step 1: Write conftest.py**

`tests/conftest.py`:
```python
import pytest
from banlog.db import open_db


@pytest.fixture
def db():
    return open_db(":memory:")
```

- [ ] **Step 2: Write failing tests**

`tests/unit/test_sync.py`:
```python
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
```

- [ ] **Step 3: Run tests, verify ERRORS**

```bash
uv run pytest tests/unit/test_sync.py -v
```

- [ ] **Step 4: Implement sync.py**

`src/banlog/sync.py`:
```python
import logging
import time
from dataclasses import dataclass, field
from sqlite3 import Connection

from banlog.config import Config, FeedConfig
from banlog.feeds import FEED_REGISTRY
from banlog import nft

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
    orphans = [(r["source"], r["service"]) for r in active if (r["source"], r["service"]) not in enabled]
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
            r["ip"] for r in db.execute(
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
                    "UPDATE blocked_ips SET end_ts=? WHERE ip=? AND source=? AND service=? AND end_ts IS NULL",
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
    report.results.append(FeedSyncResult(
        source=feed_name, status="success",
        added=total_added, removed=total_removed, total=len(new_ips),
    ))
    log.info("Feed '%s': +%d -%d total=%d", feed_name, total_added, total_removed, len(new_ips))


def _rebuild_sets(config: Config, db: Connection, report: SyncReport) -> None:
    services = {
        svc
        for fc in config.feeds.values()
        for svc, sc in fc.services.items()
        if sc.enabled
    }
    for svc in sorted(services):
        ips = {r["ip"] for r in db.execute(
            "SELECT DISTINCT ip FROM blocked_ips WHERE service=? AND end_ts IS NULL", (svc,)
        )}
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
```

- [ ] **Step 5: Run tests, verify 6 passed**

```bash
uv run pytest tests/unit/test_sync.py -v
```

- [ ] **Step 6: Run full unit suite**

```bash
uv run pytest tests/unit/ -v
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/banlog/sync.py tests/unit/test_sync.py tests/conftest.py
git commit -m "feat: add sync engine with orphan cleanup and nft rebuild"
```

---

## Task 8: CLI

**Files:**
- Create: `src/banlog/cli.py`

- [ ] **Step 1: Implement cli.py**

`src/banlog/cli.py`:
```python
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
```

- [ ] **Step 2: Verify CLI entry point**

```bash
uv run banlog --help
```

Expected: shows `{sync,status,history,list,feeds}` subcommands

- [ ] **Step 3: Test invalid IP exits 2**

```bash
uv run banlog --db :memory: history --ip not_an_ip
echo "exit: $?"
```

Expected: `ERROR Invalid IP address: not_an_ip` and `exit: 2`

- [ ] **Step 4: Run full unit suite with coverage**

```bash
uv run pytest tests/unit/ --cov=banlog --cov-report=term-missing
```

Expected: ≥80% coverage, all pass

- [ ] **Step 5: Commit**

```bash
git add src/banlog/cli.py
git commit -m "feat: add CLI with sync/status/history/list/feeds subcommands"
```

---

## Task 9: Integration test, CI, docs

**Files:**
- Create: `tests/integration/test_sync_e2e.py`
- Create: `.github/workflows/ci.yml`
- Create: `config/lists.example.json`
- Create: `scripts/smoke-test.sh`
- Create: `README.md`

- [ ] **Step 1: Write integration test**

`tests/integration/test_sync_e2e.py`:
```python
"""
Integration test: real SQLite + real HTTP server + real nft (if available).
Run with: pytest -m integration
"""
import http.server
import json
import shutil
import subprocess
import threading
import pytest
from banlog.config import load_config
from banlog.db import open_db
from banlog import nft, sync

pytestmark = pytest.mark.integration

NFT_AVAILABLE = shutil.which("nft") is not None
FIXTURE_CSV = b"1.2.3.4,tag\n5.6.7.8,tag\n10.0.0.1,tag\n"


@pytest.fixture
def http_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(FIXTURE_CSV)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}/feed.csv"
    server.shutdown()


@pytest.fixture
def tmp_config(tmp_path, http_server):
    cfg = {
        "feeds": {
            "test_feed": {
                "type": "turris",
                "url": http_server,
                "refresh_minutes": 60,
                "services": {"ssh": {"enabled": True}},
            }
        }
    }
    p = tmp_path / "lists.json"
    p.write_text(json.dumps(cfg))
    return str(p)


@pytest.mark.skipif(not NFT_AVAILABLE, reason="nft not available")
def test_full_sync_populates_db_and_nft_set(tmp_path, tmp_config, monkeypatch):
    monkeypatch.setattr("banlog.nft.TABLE", "inet banlog_test")
    subprocess.run(["nft", "add", "table", "inet", "banlog_test"], check=True)
    try:
        config = load_config(tmp_config)
        db = open_db(str(tmp_path / "test.db"))
        nft.ensure_table_and_sets(["ssh"])
        report = sync.run_sync(config, db)

        assert report.results[0].status == "success"
        assert report.results[0].added == 3

        active = {r["ip"] for r in db.execute("SELECT ip FROM blocked_ips WHERE end_ts IS NULL")}
        assert active == {"1.2.3.4", "5.6.7.8", "10.0.0.1"}

        result = subprocess.run(
            ["nft", "list", "set", "inet", "banlog_test", "banlog_ssh"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "1.2.3.4" in result.stdout

        report2 = sync.run_sync(config, db)
        assert report2.results[0].added == 0
        assert report2.results[0].removed == 0
    finally:
        subprocess.run(["nft", "delete", "table", "inet", "banlog_test"], capture_output=True)
```

- [ ] **Step 2: Write CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check src/
      - run: uv run ruff format --check src/
      - run: uv run mypy src/

  test-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run pytest tests/unit/ --cov=banlog --cov-report=term-missing --cov-fail-under=80

  test-integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - name: Install nftables
        run: sudo apt-get install -y nftables
      - run: uv sync
      - run: sudo uv run pytest -m integration -v
```

- [ ] **Step 3: Write example config**

`config/lists.example.json`:
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

- [ ] **Step 4: Write smoke-test.sh**

`scripts/smoke-test.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

echo "==> banlog status"
banlog status

echo "==> nft set exists"
nft list set inet banlog banlog_ssh

echo "==> history lookup (empty result is ok)"
banlog history --ip 8.8.8.8

echo "==> last sync_run is success"
sqlite3 /var/lib/banlog/banlog.db \
  "SELECT status FROM sync_runs ORDER BY id DESC LIMIT 1;" | grep -q "^success$"

echo "All smoke tests passed."
```

```bash
chmod +x scripts/smoke-test.sh
```

- [ ] **Step 5: Write README.md**

`README.md`:
```markdown
# banlog

Maintains nftables IP blocklist sets from external feeds with a SQLite audit trail.

## Install

```bash
# via pipx
pipx install banlog

# via uv
uv tool install banlog
```

## Setup

```bash
sudo mkdir -p /etc/banlog /var/lib/banlog
sudo cp config/lists.example.json /etc/banlog/lists.json
# Edit /etc/banlog/lists.json to enable the feeds and services you need
```

## Usage

```bash
sudo banlog sync                        # fetch feeds, update nft sets
banlog status                           # active block counts per feed/service
banlog history --ip 1.2.3.4            # block history for an IP
banlog list --service ssh               # active IPs for a service
banlog feeds                            # show configured feeds
```

Global flags: `--config PATH`, `--db PATH`, `--log-level LEVEL`

## Wire into nftables

After first sync, reference the sets in your firewall rules:

```
table inet filter {
    chain input {
        type filter hook input priority 0; policy accept;
        ip saddr @banlog_ssh   tcp dport 22  drop
        ip saddr @banlog_https tcp dport 443 drop
    }
}
```

The `inet banlog` table must exist before loading these rules:

```bash
sudo banlog sync        # creates table and sets
sudo nft -f /etc/nftables.conf
```

## Systemd timer

```ini
# /etc/systemd/system/banlog.service
[Unit]
Description=banlog blocklist sync
[Service]
Type=oneshot
ExecStart=/usr/local/bin/banlog sync
```

```ini
# /etc/systemd/system/banlog.timer
[Unit]
Description=Run banlog every hour
[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now banlog.timer
```

## Troubleshooting

**`nft: No such table`** — run `sudo banlog sync` first to create the table and sets.

**`database is locked`** — a sync is running; `busy_timeout = 5000` retries automatically for 5 s.

**Schema version error** — the DB was written by a newer banlog. Upgrade the binary.

## Dev

```bash
uv sync
uv run pytest tests/unit/ --cov=banlog
uv run ruff check src/ && uv run ruff format --check src/
uv run mypy src/
```
```

- [ ] **Step 6: Final lint + type check**

```bash
uv run ruff check src/ && uv run ruff format --check src/ && uv run mypy src/
```

Expected: no errors

- [ ] **Step 7: Final unit test run**

```bash
uv run pytest tests/unit/ --cov=banlog --cov-report=term-missing
```

Expected: all pass, coverage ≥80%

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "feat: add integration test, CI, README, example config, smoke script"
```
