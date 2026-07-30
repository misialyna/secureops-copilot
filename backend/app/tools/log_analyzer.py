import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.tools.registry import ToolResult, ToolSpec, register_tool

MAX_SAMPLE_LINES = 3
BRUTE_FORCE_THRESHOLD = 10
BRUTE_FORCE_WINDOW_SECONDS = 5 * 60
PATH_SCAN_THRESHOLD = 10
STATUS_FINDING_THRESHOLD = 5

_SYSLOG_PREFIX = re.compile(r"^(?P<ts>\w{3}\s+\d{1,2} \d{2}:\d{2}:\d{2})\s+\S+\s+\S+?:\s*(?P<msg>.*)$")
_FAILED_PASSWORD = re.compile(
    r"Failed password for (?:invalid user )?(?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
)
_ACCEPTED = re.compile(
    r"Accepted \S+ for (?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
)
_NEW_USER = re.compile(r"new user: name=(?P<user>[^,]+),")
_SUDO_GRANT = re.compile(r"add '(?P<user>[^']+)' to group '(?:sudo|wheel)'")

_ACCESS_LOG_LINE = re.compile(
    r'^(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)[^"]*"\s+(?P<status>\d{3})\s+\S+'
    r'(?:\s+"(?P<referer>[^"]*)"\s+"(?P<agent>[^"]*)")?'
)

_SUSPICIOUS_USER_AGENT_KEYWORDS = (
    "sqlmap",
    "nikto",
    "nmap",
    "masscan",
    "dirbuster",
    "gobuster",
    "wpscan",
    "acunetix",
    "nessus",
)


def _parse_syslog_timestamp(ts: str) -> datetime:
    # No year or timezone in syslog timestamps; intentionally naive — only used for
    # relative deltas *within* a single log file, never compared to wall-clock time.
    return datetime.strptime(f"1900 {ts}", "%Y %b %d %H:%M:%S")  # noqa: DTZ007


def _looks_like_access_log(lines: list[str]) -> bool:
    sample = [line for line in lines[:20] if line.strip()]
    if not sample:
        return False
    matches = sum(1 for line in sample if _ACCESS_LOG_LINE.match(line))
    return matches >= len(sample) / 2


def _looks_like_auth_log(lines: list[str]) -> bool:
    sample = [line for line in lines[:20] if line.strip()]
    if not sample:
        return False
    matches = sum(1 for line in sample if _SYSLOG_PREFIX.match(line))
    return matches >= len(sample) / 2


def _analyze_auth_log(lines: list[str]) -> ToolResult:
    failed_events: list[tuple[datetime, str, str, str]] = []  # (ts, ip, user, line)
    accepted_events: list[tuple[datetime, str, str, str]] = []
    account_changes: list[dict[str, Any]] = []

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        prefix_match = _SYSLOG_PREFIX.match(line)
        if not prefix_match:
            continue
        ts = _parse_syslog_timestamp(prefix_match.group("ts"))
        msg = prefix_match.group("msg")

        if match := _FAILED_PASSWORD.search(msg):
            failed_events.append((ts, match.group("ip"), match.group("user"), line))
        elif match := _ACCEPTED.search(msg):
            accepted_events.append((ts, match.group("ip"), match.group("user"), line))
        elif match := _NEW_USER.search(msg):
            account_changes.append(
                {
                    "change_type": "new_account",
                    "username": match.group("user"),
                    "timestamp": ts.isoformat(),
                    "sample_lines": [line],
                }
            )
        elif match := _SUDO_GRANT.search(msg):
            account_changes.append(
                {
                    "change_type": "sudo_granted",
                    "username": match.group("user"),
                    "timestamp": ts.isoformat(),
                    "sample_lines": [line],
                }
            )

    failed_by_ip: dict[str, list[tuple[datetime, str, str]]] = defaultdict(list)
    for ts, ip, user, line in failed_events:
        failed_by_ip[ip].append((ts, user, line))

    brute_force_findings: list[dict[str, Any]] = []
    brute_force_ips: set[str] = set()
    for ip, events in failed_by_ip.items():
        events.sort(key=lambda e: e[0])
        left = 0
        for right in range(len(events)):
            while (events[right][0] - events[left][0]).total_seconds() > BRUTE_FORCE_WINDOW_SECONDS:
                left += 1
            window = events[left : right + 1]
            if len(window) >= BRUTE_FORCE_THRESHOLD:
                brute_force_ips.add(ip)
                brute_force_findings.append(
                    {
                        "ip": ip,
                        "failed_count": len(window),
                        "window_start": window[0][0].isoformat(),
                        "window_end": window[-1][0].isoformat(),
                        "usernames_tried": sorted({e[1] for e in window}),
                        "sample_lines": [e[2] for e in window[:MAX_SAMPLE_LINES]],
                    }
                )
                break

    critical_findings: list[dict[str, Any]] = []
    for ts, ip, user, line in accepted_events:
        if ip in brute_force_ips:
            critical_findings.append(
                {
                    "severity": "critical",
                    "ip": ip,
                    "username": user,
                    "timestamp": ts.isoformat(),
                    "sample_lines": [line],
                    "note": "Successful login from an IP that was also brute-forcing this host.",
                }
            )

    findings = brute_force_findings + critical_findings + account_changes
    warnings = []
    if not findings:
        warnings.append("No brute-force, suspicious login, or account-change patterns detected.")

    summary_parts = [
        f"{len(brute_force_findings)} brute-force source IP(s)",
        f"{len(critical_findings)} successful login(s) after brute force",
        f"{len(account_changes)} account/privilege change(s)",
    ]
    return ToolResult(
        tool_name="log_analyzer",
        summary="auth.log analysis: " + ", ".join(summary_parts),
        findings=findings,
        warnings=warnings,
    )


def _analyze_access_log(lines: list[str]) -> ToolResult:
    request_count_by_ip: dict[str, int] = defaultdict(int)
    status_count_by_ip: dict[tuple[str, str], int] = defaultdict(int)
    not_found_paths_by_ip: dict[str, list[str]] = defaultdict(list)
    user_agents_by_ip: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        match = _ACCESS_LOG_LINE.match(line)
        if not match:
            continue
        ip = match.group("ip")
        status = match.group("status")
        path = match.group("path")
        agent = match.group("agent") or ""

        request_count_by_ip[ip] += 1
        status_class = f"{status[0]}xx"
        if status_class in ("4xx", "5xx"):
            status_count_by_ip[(ip, status_class)] += 1
        if status == "404":
            not_found_paths_by_ip[ip].append(path)
        if agent:
            user_agents_by_ip[ip][agent] += 1

    top_ips = sorted(request_count_by_ip.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_ip_findings = [
        {"finding_type": "top_ip", "ip": ip, "request_count": count} for ip, count in top_ips
    ]

    status_findings = [
        {
            "finding_type": "status_code",
            "ip": ip,
            "status_class": status_class,
            "count": count,
        }
        for (ip, status_class), count in status_count_by_ip.items()
        if count >= STATUS_FINDING_THRESHOLD
    ]

    path_scan_findings = [
        {
            "finding_type": "path_scan",
            "ip": ip,
            "count_404": len(paths),
            "sample_paths": paths[:MAX_SAMPLE_LINES],
        }
        for ip, paths in not_found_paths_by_ip.items()
        if len(paths) >= PATH_SCAN_THRESHOLD
    ]

    suspicious_agent_findings = [
        {
            "finding_type": "suspicious_user_agent",
            "ip": ip,
            "user_agent": agent,
            "count": count,
        }
        for ip, agents in user_agents_by_ip.items()
        for agent, count in agents.items()
        if any(keyword in agent.lower() for keyword in _SUSPICIOUS_USER_AGENT_KEYWORDS)
    ]

    findings = top_ip_findings + status_findings + path_scan_findings + suspicious_agent_findings
    warnings = []
    if not path_scan_findings and not suspicious_agent_findings:
        warnings.append("No path-scanning or suspicious user-agent activity detected.")

    summary = (
        f"access log analysis: {len(request_count_by_ip)} distinct IP(s), "
        f"{len(path_scan_findings)} likely path-scanning source(s), "
        f"{len(suspicious_agent_findings)} suspicious user-agent hit(s)"
    )
    return ToolResult(
        tool_name="log_analyzer", summary=summary, findings=findings, warnings=warnings
    )


def analyze_log_file(file_path: str) -> ToolResult:
    lines = Path(file_path).read_text(errors="replace").splitlines(keepends=True)

    if _looks_like_access_log(lines):
        return _analyze_access_log(lines)
    if _looks_like_auth_log(lines):
        return _analyze_auth_log(lines)
    return ToolResult(
        tool_name="log_analyzer",
        summary="Could not identify log format (expected auth.log/syslog or a combined access log).",
        findings=[],
        warnings=["Unrecognized log format; no analysis performed."],
    )


register_tool(
    ToolSpec(
        name="log_analyzer",
        description=(
            "Analyzes a text log file uploaded as evidence: either an SSH/syslog auth.log "
            "(detects SSH brute force, successful logins from brute-forcing IPs, new "
            "accounts/sudo grants) or a web server access log (top IPs, 4xx/5xx per IP, "
            "path-scanning, suspicious user agents). The log format is auto-detected."
        ),
        risk_level="read_only",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the uploaded evidence log file to analyze.",
                }
            },
            "required": ["file_path"],
        },
    ),
    analyze_log_file,
)
