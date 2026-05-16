from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from banlog.feeds.base import FeedParser

FEED_REGISTRY: dict[str, type["FeedParser"]] = {}
