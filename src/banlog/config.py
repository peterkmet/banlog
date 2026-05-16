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
