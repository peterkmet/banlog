import pytest
from banlog.utils import parse_ip


def test_valid_ip():
    assert parse_ip("1.2.3.4") == "1.2.3.4"


def test_normalizes_leading_zeros():
    assert parse_ip("01.02.03.04") == "1.2.3.4"


def test_rejects_invalid_string():
    with pytest.raises(ValueError):
        parse_ip("not_an_ip")


def test_rejects_ipv6():
    with pytest.raises(ValueError):
        parse_ip("::1")


def test_rejects_out_of_range():
    with pytest.raises(ValueError):
        parse_ip("999.0.0.1")


def test_rejects_empty():
    with pytest.raises(ValueError):
        parse_ip("")
