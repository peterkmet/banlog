"""
Integration test: real SQLite + real HTTP server + real nft (if available).
Run with: pytest -m integration
"""
import http.server
import json
import shutil
import subprocess
import threading
from typing import Generator

import pytest

from banlog.config import load_config
from banlog.db import open_db
from banlog import nft, sync

pytestmark = pytest.mark.integration

NFT_AVAILABLE = shutil.which("nft") is not None
FIXTURE_CSV = b"1.2.3.4,tag\n5.6.7.8,tag\n10.0.0.1,tag\n"


@pytest.fixture
def http_server() -> Generator[str, None, None]:
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
def tmp_config(tmp_path, http_server) -> str:
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
def test_full_sync_populates_db_and_nft_set(tmp_path, tmp_config, monkeypatch) -> None:
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
