from __future__ import annotations

import ipaddress
from pathlib import Path

from app.paths import PROJECT_ROOT


SELECTEL_TARGETS_PATH = PROJECT_ROOT / "resources" / "selectel" / "whitelist.txt"


def load_selectel_default_ranges(path: Path = SELECTEL_TARGETS_PATH) -> list[str]:
    """Load unique Selectel target IPs and CIDR blocks from the bundled resource file."""
    if not path.exists():
        return []

    entries: list[str] = []
    seen: set[str] = set()

    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            value = raw_line.strip()
            if not value or value.startswith("#"):
                continue

            try:
                normalized = str(ipaddress.ip_network(value, strict=False))
            except ValueError:
                continue

            if normalized in seen:
                continue

            seen.add(normalized)
            entries.append(value)
    except OSError:
        return []

    return entries