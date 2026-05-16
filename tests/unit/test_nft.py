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
