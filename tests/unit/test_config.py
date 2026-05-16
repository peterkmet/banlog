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
