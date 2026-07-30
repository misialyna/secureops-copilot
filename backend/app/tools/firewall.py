"""block_ip: an *active* tool that proposes host-firewall commands to block an IP address.

This never executes anything on its own — it only returns ready-to-run commands (ufw,
iptables, and nft variants), a description of the effect, and a rollback command. Actual
execution is gated by the human-approval flow: registry.execute_tool() refuses to run any
risk_level="active" tool without an approved ApprovalDecision, regardless of what calls it.
"""

from ipaddress import ip_address

from app.tools.registry import ToolResult, ToolSpec, register_tool


def block_ip(ip: str) -> ToolResult:
    try:
        parsed = ip_address(ip)
    except ValueError:
        return ToolResult(
            tool_name="block_ip",
            summary=f"Invalid IP address: {ip!r}",
            warnings=[f"{ip!r} is not a valid IPv4 or IPv6 address."],
        )

    if parsed.is_private or parsed.is_loopback or parsed.is_link_local:
        return ToolResult(
            tool_name="block_ip",
            summary=f"Refused to propose blocking {ip}: private/loopback/link-local address.",
            warnings=[
                (
                    f"{ip} is a private, loopback, or link-local address. Blocking it would "
                    "likely disrupt internal network traffic rather than stop an external "
                    "attacker — this looks like an operational mistake, so no commands were "
                    "generated. Double-check the IP before retrying with a public address."
                )
            ],
        )

    is_v6 = parsed.version == 6
    iptables_bin = "ip6tables" if is_v6 else "iptables"
    nft_family = "ip6" if is_v6 else "ip"

    ufw_command = f"ufw deny from {ip} to any"
    ufw_rollback = f"ufw delete deny from {ip} to any"
    iptables_command = f"{iptables_bin} -A INPUT -s {ip} -j DROP"
    iptables_rollback = f"{iptables_bin} -D INPUT -s {ip} -j DROP"
    nft_command = f"nft add rule inet filter input {nft_family} saddr {ip} drop"
    nft_rollback = (
        f"nft -a list chain inet filter input   # find the handle for the rule matching {ip}, then:\n"
        "nft delete rule inet filter input handle <handle>"
    )

    return ToolResult(
        tool_name="block_ip",
        summary=f"Proposed firewall block for {ip} (ufw, iptables, and nft variants).",
        findings=[
            {
                "ip": ip,
                "ufw_command": ufw_command,
                "ufw_rollback": ufw_rollback,
                "iptables_command": iptables_command,
                "iptables_rollback": iptables_rollback,
                "nft_command": nft_command,
                "nft_rollback": nft_rollback,
                "effect": (
                    f"Drops all inbound traffic from {ip} at the host firewall. Already-"
                    "established connections may not be reset immediately; this does not "
                    f"block outbound traffic to {ip}."
                ),
            }
        ],
        warnings=[
            (
                "These are proposed commands only — nothing has been executed. Run the one "
                "matching your host's firewall (ufw, iptables, or nft), not all three."
            )
        ],
    )


register_tool(
    ToolSpec(
        name="block_ip",
        description=(
            "Proposes host-firewall commands (ufw, iptables, and nft variants) to block all "
            "inbound traffic from a given public IP address, along with a rollback command. "
            "Never executes anything itself — this is an active/risky action that requires "
            "human approval before the returned commands may be run. Refuses private/"
            "loopback/link-local addresses (likely an operational mistake)."
        ),
        risk_level="active",
        input_schema={
            "type": "object",
            "properties": {
                "ip": {
                    "type": "string",
                    "description": "Public IPv4 or IPv6 address to propose blocking.",
                }
            },
            "required": ["ip"],
        },
    ),
    block_ip,
)
