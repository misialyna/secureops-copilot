from pathlib import Path

from scapy.layers.dns import DNS, DNSQR
from scapy.layers.inet import IP, TCP, UDP
from scapy.utils import wrpcap

from app.config import Settings
from app.tools.pcap_analyzer import analyze_pcap


def _build_test_pcap(path: Path) -> None:
    packets = []
    base = 1_700_000_000.0

    # port scan: 192.168.1.50 -> 10.0.0.5 across 20 ports, half a second apart
    for i, port in enumerate(range(20, 40)):
        pkt = IP(src="192.168.1.50", dst="10.0.0.5") / TCP(sport=40000 + i, dport=port, flags="S")
        pkt.time = base + i * 0.5
        packets.append(pkt)

    # beaconing: 192.168.1.60 -> 8.8.4.4 every 30s, 6 times
    for i in range(6):
        pkt = IP(src="192.168.1.60", dst="8.8.4.4") / TCP(sport=50000, dport=443, flags="S")
        pkt.time = base + 1000 + i * 30.0
        packets.append(pkt)

    # suspicious long DNS query, repeated
    long_domain = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0.evil-tunnel.example.com"
    for i in range(3):
        pkt = IP(src="192.168.1.70", dst="8.8.8.8") / UDP(sport=53000, dport=53) / DNS(
            rd=1, qd=DNSQR(qname=long_domain)
        )
        pkt.time = base + 2000 + i
        packets.append(pkt)

    wrpcap(str(path), packets)


def test_analyze_pcap_detects_port_scan_beaconing_and_suspicious_dns(tmp_path: Path) -> None:
    pcap_path = tmp_path / "capture.pcap"
    _build_test_pcap(pcap_path)

    result = analyze_pcap(str(pcap_path))

    stats = next(f for f in result.findings if f["finding_type"] == "stats")
    assert stats["packet_count"] == 29

    port_scan = [f for f in result.findings if f["finding_type"] == "port_scan"]
    assert len(port_scan) == 1
    assert port_scan[0]["src_ip"] == "192.168.1.50"
    assert port_scan[0]["dst_ip"] == "10.0.0.5"
    assert port_scan[0]["distinct_ports"] >= 15

    beaconing = [f for f in result.findings if f["finding_type"] == "beaconing"]
    assert len(beaconing) == 1
    assert beaconing[0]["src_ip"] == "192.168.1.60"
    assert beaconing[0]["mean_interval_seconds"] == 30.0

    dns_findings = [f for f in result.findings if f["finding_type"] == "suspicious_dns"]
    assert len(dns_findings) == 1
    assert "evil-tunnel.example.com" in dns_findings[0]["domain"]

    top_talkers = [f for f in result.findings if f["finding_type"] == "top_talker"]
    assert len(top_talkers) >= 1


def test_analyze_pcap_rejects_oversized_file(tmp_path: Path) -> None:
    pcap_path = tmp_path / "capture.pcap"
    _build_test_pcap(pcap_path)

    result = analyze_pcap(str(pcap_path), settings=Settings(max_evidence_file_size_mb=0))

    assert result.findings == []
    assert result.warnings
    assert "too large" in result.summary.lower() or "limit" in result.summary.lower()
