from __future__ import annotations

from .models import RollerStats, SubnetInsight


def format_uptime(seconds: int) -> str:
    hours, remainder = divmod(max(seconds, 0), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_rate_summary(stats: RollerStats) -> str:
    return (
        f"APM {stats.attempts_per_minute:.1f} | "
        f"Success {stats.success_rate_percent:.1f}% | "
        f"Unique IPs {stats.unique_ip_count} | "
        f"Deleted {stats.deleted_resources}"
    )


def format_top_subnets(subnets: list[SubnetInsight]) -> str:
    if not subnets:
        return "No subnet data yet."

    lines = []
    for index, subnet in enumerate(subnets, start=1):
        label = "target" if subnet.category == "configured" else "observed"
        lines.append(
            f"{index}. {subnet.network} x{subnet.count} ({subnet.share_percent:.1f}%, {label})"
        )
    return "\n".join(lines)