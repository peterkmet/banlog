import json
import pytest
from banlog.cli import cmd_history, cmd_status, cmd_feeds, cmd_list
from banlog.db import open_db


class FakeArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def populated_db(tmp_path):
    db = open_db(str(tmp_path / "test.db"))
    db.execute(
        "INSERT INTO blocked_ips(ip, source, service, start_ts) VALUES (?,?,?,?)",
        ("1.2.3.4", "turris_greylist", "ssh", 1000),
    )
    db.execute(
        "INSERT INTO sync_runs(source, started_ts, finished_ts, status, added, total) VALUES (?,?,?,?,?,?)",
        ("turris_greylist", 900, 1000, "success", 1, 1),
    )
    db.commit()
    return db


def test_history_invalid_ip_exits_2(tmp_path):
    args = FakeArgs(ip="not_an_ip", db=str(tmp_path / "test.db"))
    assert cmd_history(args) == 2


def test_history_valid_ip_no_results(tmp_path, capsys):
    db_path = str(tmp_path / "test.db")
    open_db(db_path)
    args = FakeArgs(ip="1.2.3.4", db=db_path)
    result = cmd_history(args)
    assert result == 0
    assert "No history" in capsys.readouterr().out


def test_history_valid_ip_with_results(tmp_path, populated_db, capsys):
    args = FakeArgs(ip="1.2.3.4", db=str(tmp_path / "test.db"))
    result = cmd_history(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "turris_greylist" in out


def test_status_empty_db(tmp_path, capsys):
    db_path = str(tmp_path / "test.db")
    open_db(db_path)
    args = FakeArgs(db=db_path)
    result = cmd_status(args)
    assert result == 0
    assert "No active" in capsys.readouterr().out


def test_status_with_data(tmp_path, populated_db, capsys):
    args = FakeArgs(db=str(tmp_path / "test.db"))
    result = cmd_status(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "turris_greylist" in out


def test_feeds_lists_configured_feeds(tmp_path, capsys):
    cfg = {
        "feeds": {
            "turris_greylist": {
                "type": "turris",
                "url": "http://example.com",
                "refresh_minutes": 60,
                "services": {"ssh": {"enabled": True}},
            }
        }
    }
    config_path = str(tmp_path / "lists.json")
    (tmp_path / "lists.json").write_text(json.dumps(cfg))
    args = FakeArgs(config=config_path)
    result = cmd_feeds(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "turris_greylist" in out
    assert "turris" in out


def test_list_active_only(tmp_path, populated_db, capsys):
    args = FakeArgs(db=str(tmp_path / "test.db"), service="ssh", source=None, all=False)
    result = cmd_list(args)
    assert result == 0
    assert "1.2.3.4" in capsys.readouterr().out


def test_list_all_includes_ended(tmp_path, capsys):
    db_path = str(tmp_path / "test.db")
    db = open_db(db_path)
    db.execute(
        "INSERT INTO blocked_ips(ip, source, service, start_ts, end_ts) VALUES (?,?,?,?,?)",
        ("9.9.9.9", "turris", "ssh", 100, 200),
    )
    db.commit()
    args = FakeArgs(db=db_path, service="ssh", source=None, all=True)
    result = cmd_list(args)
    assert result == 0
    assert "9.9.9.9" in capsys.readouterr().out
