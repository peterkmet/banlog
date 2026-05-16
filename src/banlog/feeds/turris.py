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
