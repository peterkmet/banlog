from banlog.feeds.base import FeedParser
from banlog.feeds.turris import TurrisFeed

FEED_REGISTRY: dict[str, type[FeedParser]] = {
    "turris": TurrisFeed,
}
