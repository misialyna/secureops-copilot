from pathlib import Path

from app.tools.log_analyzer import analyze_log_file

_AUTH_LOG_LINES = [
    "Jan 12 03:14:01 web01 sshd[1001]: Failed password for invalid user admin from 203.0.113.5 port 51001 ssh2",
    "Jan 12 03:14:10 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51002 ssh2",
    "Jan 12 03:14:20 web01 sshd[1001]: Failed password for admin from 203.0.113.5 port 51003 ssh2",
    "Jan 12 03:14:30 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51004 ssh2",
    "Jan 12 03:14:40 web01 sshd[1001]: Failed password for test from 203.0.113.5 port 51005 ssh2",
    "Jan 12 03:14:50 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51006 ssh2",
    "Jan 12 03:15:00 web01 sshd[1001]: Failed password for admin from 203.0.113.5 port 51007 ssh2",
    "Jan 12 03:15:10 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51008 ssh2",
    "Jan 12 03:15:20 web01 sshd[1001]: Failed password for guest from 203.0.113.5 port 51009 ssh2",
    "Jan 12 03:15:30 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51010 ssh2",
    "Jan 12 03:15:40 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51011 ssh2",
    "Jan 12 03:16:00 web01 sshd[1002]: Accepted password for root from 203.0.113.5 port 51050 ssh2",
    "Jan 12 03:20:00 web01 sshd[1010]: Failed password for bob from 198.51.100.9 port 40001 ssh2",
    "Jan 12 03:25:00 web01 useradd[2001]: new user: name=eve, UID=1002, GID=1002, home=/home/eve, shell=/bin/bash",
    "Jan 12 03:26:00 web01 usermod[2002]: add 'eve' to group 'sudo'",
]


def _write(tmp_path: Path, name: str, lines: list[str]) -> str:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_auth_log_detects_brute_force_and_success_after(tmp_path: Path) -> None:
    path = _write(tmp_path, "auth.log", _AUTH_LOG_LINES)

    result = analyze_log_file(path)

    brute_force = [f for f in result.findings if f.get("ip") == "203.0.113.5" and "failed_count" in f]
    assert len(brute_force) == 1
    assert brute_force[0]["failed_count"] == 10
    assert len(brute_force[0]["sample_lines"]) <= 3

    critical = [f for f in result.findings if f.get("severity") == "critical"]
    assert len(critical) == 1
    assert critical[0]["ip"] == "203.0.113.5"
    assert critical[0]["username"] == "root"

    # a single failed attempt from another IP must not be flagged as brute force
    assert not any(f.get("ip") == "198.51.100.9" and "failed_count" in f for f in result.findings)


def test_auth_log_detects_account_changes(tmp_path: Path) -> None:
    path = _write(tmp_path, "auth.log", _AUTH_LOG_LINES)

    result = analyze_log_file(path)

    new_accounts = [f for f in result.findings if f.get("change_type") == "new_account"]
    sudo_grants = [f for f in result.findings if f.get("change_type") == "sudo_granted"]
    assert new_accounts == [
        {
            "change_type": "new_account",
            "username": "eve",
            "timestamp": "1900-01-12T03:25:00",
            "sample_lines": [_AUTH_LOG_LINES[13]],
        }
    ]
    assert sudo_grants[0]["username"] == "eve"


def test_access_log_detects_path_scan_and_suspicious_agent(tmp_path: Path) -> None:
    scanner_ip = "198.51.100.50"
    paths = [
        "/wp-admin/",
        "/.env",
        "/admin/",
        "/phpmyadmin/",
        "/.git/config",
        "/config.php",
        "/backup.zip",
        "/wp-login.php",
        "/xmlrpc.php",
        "/.aws/credentials",
        "/server-status",
        "/test.php",
    ]
    lines = [
        f'{scanner_ip} - - [12/Jan/2024:03:14:{i:02d} +0000] "GET {p} HTTP/1.1" 404 512 "-" "sqlmap/1.6"'
        for i, p in enumerate(paths)
    ]
    normal_ip = "203.0.113.10"
    lines += [
        f'{normal_ip} - - [12/Jan/2024:03:20:{i:02d} +0000] "GET /index.html HTTP/1.1" 200 2048 "-" "Mozilla/5.0"'
        for i in range(5)
    ]
    path = _write(tmp_path, "access.log", lines)

    result = analyze_log_file(path)

    path_scan = [f for f in result.findings if f.get("finding_type") == "path_scan"]
    assert path_scan == [
        {
            "finding_type": "path_scan",
            "ip": scanner_ip,
            "count_404": 12,
            "sample_paths": paths[:3],
        }
    ]

    suspicious_agents = [f for f in result.findings if f.get("finding_type") == "suspicious_user_agent"]
    assert suspicious_agents == [
        {
            "finding_type": "suspicious_user_agent",
            "ip": scanner_ip,
            "user_agent": "sqlmap/1.6",
            "count": 12,
        }
    ]

    top_ips = {f["ip"]: f["request_count"] for f in result.findings if f.get("finding_type") == "top_ip"}
    assert top_ips[scanner_ip] == 12
    assert top_ips[normal_ip] == 5


def test_unrecognized_log_format_returns_warning(tmp_path: Path) -> None:
    path = _write(tmp_path, "mystery.log", ["this is not a recognizable log line", "neither is this"])

    result = analyze_log_file(path)

    assert result.findings == []
    assert result.warnings
