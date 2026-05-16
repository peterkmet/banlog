import pytest
from banlog.feeds.turris import TurrisFeed

VALID_CSV = b"# comment\n1.2.3.4,some_tag\n5.6.7.8,other_tag\n10.0.0.1,tag3\n"
IPV6_CSV = b"1.2.3.4,tag\n::1,ipv6\n2001:db8::1,ipv6\n"
MALFORMED_CSV = b"1.2.3.4,tag\nnot_an_ip,tag\n999.999.999.999,tag\n5.6.7.8,tag\n"


def test_parse_valid_csv():
    assert TurrisFeed().parse(VALID_CSV) == {"1.2.3.4", "5.6.7.8", "10.0.0.1"}


def test_parse_empty():
    assert TurrisFeed().parse(b"") == set()


def test_parse_comments_only():
    assert TurrisFeed().parse(b"# comment\n") == set()


def test_parse_drops_ipv6():
    result = TurrisFeed().parse(IPV6_CSV)
    assert "::1" not in result
    assert "2001:db8::1" not in result
    assert "1.2.3.4" in result


def test_parse_drops_malformed():
    result = TurrisFeed().parse(MALFORMED_CSV)
    assert "not_an_ip" not in result
    assert "999.999.999.999" not in result
    assert {"1.2.3.4", "5.6.7.8"}.issubset(result)


def test_fetch_makes_http_request(requests_mock):
    requests_mock.get("http://example.com/feed.csv", content=VALID_CSV)
    assert TurrisFeed().fetch("http://example.com/feed.csv") == VALID_CSV


def test_registry_contains_turris():
    from banlog.feeds import FEED_REGISTRY
    assert "turris" in FEED_REGISTRY
