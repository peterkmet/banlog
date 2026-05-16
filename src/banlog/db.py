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
