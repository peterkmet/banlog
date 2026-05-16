import ipaddress


def parse_ip(value: str) -> str:
    # Strip leading zeros from each octet to normalize the input
    normalized = ".".join(str(int(octet)) for octet in value.split("."))
    return str(ipaddress.IPv4Address(normalized))
