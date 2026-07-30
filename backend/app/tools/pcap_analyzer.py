import statistics
from collections import defaultdict
from datetime import UTC, datetime
from ipaddress import ip_address
from itertools import pairwise
from pathlib import Path
from typing import Any

from scapy.layers.dns import DNSQR
from scapy.layers.inet import IP, TCP, UDP
from scapy.utils import rdpcap

from app.config import Settings
from app.tools.registry import ToolResult, ToolSpec, register_tool

TOP_N = 5
PORT_SCAN_MIN_DISTINCT_PORTS = 15
PORT_SCAN_WINDOW_SECONDS = 60.0
BEACON_MIN_CONNECTIONS = 5
BEACON_MAX_RELATIVE_STDDEV = 0.2
SUSPICIOUS_DNS_MIN_LENGTH = 40
SUSPICIOUS_DNS_MIN_QUERY_COUNT = 20


def _is_internal(ip: str) -> bool:
    try:
        return ip_address(ip).is_private
    except ValueError:
        return False


def analyze_pcap(file_path: str, settings: Settings | None = None) -> ToolResult:
    settings = settings or Settings()
    size_mb = Path(file_path).stat().st_size / (1024 * 1024)
    if size_mb > settings.max_evidence_file_size_mb:
        limit = settings.max_evidence_file_size_mb
        return ToolResult(
            tool_name="pcap_analyzer",
            summary=f"PCAP file too large ({size_mb:.1f} MB, limit is {limit} MB) — not analyzed.",
            findings=[],
            warnings=[f"File exceeds the {limit} MB analysis limit and was skipped."],
        )

    packets = rdpcap(file_path)

    talker_counts: dict[tuple[str, str], int] = defaultdict(int)
    port_counts: dict[int, int] = defaultdict(int)
    port_events: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
    dns_query_counts: dict[str, int] = defaultdict(int)
    timestamps: list[float] = []

    for pkt in packets:
        if IP not in pkt:
            continue
        ts = float(pkt.time)
        timestamps.append(ts)
        src, dst = pkt[IP].src, pkt[IP].dst
        talker_counts[tuple(sorted((src, dst)))] += 1

        dst_port: int | None = None
        if TCP in pkt:
            dst_port = int(pkt[TCP].dport)
        elif UDP in pkt:
            dst_port = int(pkt[UDP].dport)
        if dst_port is not None:
            port_counts[dst_port] += 1
            port_events[(src, dst)].append((ts, dst_port))

        if pkt.haslayer(DNSQR):
            qname = pkt[DNSQR].qname
            if isinstance(qname, bytes):
                qname = qname.decode(errors="replace")
            qname = qname.rstrip(".")
            if qname:
                dns_query_counts[qname] += 1

    top_talker_findings = [
        {"finding_type": "top_talker", "ip_a": a, "ip_b": b, "packet_count": count}
        for (a, b), count in sorted(talker_counts.items(), key=lambda kv: kv[1], reverse=True)[
            :TOP_N
        ]
    ]
    top_port_findings = [
        {"finding_type": "top_port", "port": port, "packet_count": count}
        for port, count in sorted(port_counts.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
    ]

    port_scan_findings: list[dict[str, Any]] = []
    for (src, dst), events in port_events.items():
        events.sort(key=lambda e: e[0])
        left = 0
        for right in range(len(events)):
            while events[right][0] - events[left][0] > PORT_SCAN_WINDOW_SECONDS:
                left += 1
            window = events[left : right + 1]
            distinct_ports = {port for _, port in window}
            if len(distinct_ports) >= PORT_SCAN_MIN_DISTINCT_PORTS:
                port_scan_findings.append(
                    {
                        "finding_type": "port_scan",
                        "src_ip": src,
                        "dst_ip": dst,
                        "distinct_ports": len(distinct_ports),
                        "window_seconds": round(window[-1][0] - window[0][0], 2),
                        "sample_ports": sorted(distinct_ports)[:10],
                    }
                )
                break

    beaconing_findings: list[dict[str, Any]] = []
    for (src, dst), events in port_events.items():
        target_is_external = not _is_internal(dst) or not _is_internal(src)
        if not target_is_external:
            continue
        times = sorted({ts for ts, _ in events})
        if len(times) < BEACON_MIN_CONNECTIONS:
            continue
        intervals = [t2 - t1 for t1, t2 in pairwise(times)]
        mean_interval = statistics.mean(intervals)
        if mean_interval <= 0:
            continue
        stddev = statistics.pstdev(intervals) if len(intervals) > 1 else 0.0
        if stddev / mean_interval <= BEACON_MAX_RELATIVE_STDDEV:
            beaconing_findings.append(
                {
                    "finding_type": "beaconing",
                    "src_ip": src,
                    "dst_ip": dst,
                    "connection_count": len(times),
                    "mean_interval_seconds": round(mean_interval, 2),
                    "interval_stddev_seconds": round(stddev, 2),
                }
            )

    suspicious_dns_findings: list[dict[str, Any]] = []
    for domain, count in dns_query_counts.items():
        reasons = []
        if len(domain) >= SUSPICIOUS_DNS_MIN_LENGTH:
            reasons.append(f"unusually long domain name ({len(domain)} chars)")
        if count >= SUSPICIOUS_DNS_MIN_QUERY_COUNT:
            reasons.append(f"queried {count} times (possible DNS tunneling channel)")
        if reasons:
            suspicious_dns_findings.append(
                {
                    "finding_type": "suspicious_dns",
                    "domain": domain,
                    "query_count": count,
                    "reason": "; ".join(reasons),
                }
            )

    time_range = None
    if timestamps:
        time_range = {
            "start": datetime.fromtimestamp(min(timestamps), tz=UTC).isoformat(),
            "end": datetime.fromtimestamp(max(timestamps), tz=UTC).isoformat(),
        }
    stats_finding = {"finding_type": "stats", "packet_count": len(packets), "time_range": time_range}

    findings = (
        [stats_finding]
        + top_talker_findings
        + top_port_findings
        + port_scan_findings
        + beaconing_findings
        + suspicious_dns_findings
    )
    warnings = []
    if not port_scan_findings and not beaconing_findings and not suspicious_dns_findings:
        warnings.append("No port-scan, beaconing, or suspicious-DNS patterns detected.")

    summary = (
        f"pcap analysis: {len(packets)} packets, {len(port_scan_findings)} port-scan source(s), "
        f"{len(beaconing_findings)} beaconing pattern(s), "
        f"{len(suspicious_dns_findings)} suspicious DNS domain(s)"
    )
    return ToolResult(tool_name="pcap_analyzer", summary=summary, findings=findings, warnings=warnings)


register_tool(
    ToolSpec(
        name="pcap_analyzer",
        description=(
            "Analyzes a network capture (.pcap/.pcapng) uploaded as evidence, offline: packet "
            "count and time range, top talker IP pairs, top destination ports, port-scan "
            "detection (one host hitting many destination ports quickly), suspected C2 "
            "beaconing (regular-interval connections to one external IP), and suspicious DNS "
            "queries (unusually long or repeated domains, potential DGA/tunneling)."
        ),
        risk_level="read_only",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the uploaded evidence .pcap/.pcapng file to analyze.",
                }
            },
            "required": ["file_path"],
        },
    ),
    analyze_pcap,
)
