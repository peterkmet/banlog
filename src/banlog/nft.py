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
