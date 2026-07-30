import pytest

from app.tools.firewall import block_ip

_PRIVATE_OR_RESERVED_IPS = [
    "10.0.0.5",  # RFC1918
    "172.16.0.1",  # RFC1918
    "192.168.1.1",  # RFC1918
    "127.0.0.1",  # loopback
    "169.254.1.1",  # link-local
    "::1",  # IPv6 loopback
]


def test_block_ip_proposes_ufw_iptables_and_nft_for_public_ipv4() -> None:
    result = block_ip("45.83.65.12")

    assert not result.warnings or "proposed commands only" in result.warnings[0]
    finding = result.findings[0]
    assert finding["ip"] == "45.83.65.12"
    assert finding["ufw_command"] == "ufw deny from 45.83.65.12 to any"
    assert finding["ufw_rollback"] == "ufw delete deny from 45.83.65.12 to any"
    assert finding["iptables_command"] == "iptables -A INPUT -s 45.83.65.12 -j DROP"
    assert "nft_command" in finding
    assert "45.83.65.12" in finding["nft_command"]


def test_block_ip_uses_ip6tables_for_public_ipv6() -> None:
    result = block_ip("2001:4860:4860::8888")

    finding = result.findings[0]
    assert finding["iptables_command"].startswith("ip6tables")
    assert "ip6 saddr" in finding["nft_command"]


@pytest.mark.parametrize("ip", _PRIVATE_OR_RESERVED_IPS)
def test_block_ip_rejects_private_loopback_and_link_local(ip: str) -> None:
    result = block_ip(ip)

    assert result.findings == []
    assert result.warnings
    assert "private" in result.warnings[0] or "loopback" in result.warnings[0]


def test_block_ip_rejects_documentation_range() -> None:
    # RFC 5737 TEST-NET-3 — Python's ipaddress module classifies this as not globally
    # routable (is_private=True), which is the right call: it's never a real attack source.
    result = block_ip("203.0.113.5")

    assert result.findings == []
    assert result.warnings


def test_block_ip_rejects_invalid_address() -> None:
    result = block_ip("not-an-ip")

    assert result.findings == []
    assert "Invalid IP address" in result.summary
