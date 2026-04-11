from __future__ import annotations

import ipaddress
from collections import Counter

from .models import SubnetInsight


class ObservedSubnetAnalytics:
    """Track the most common subnet buckets across observed IP addresses."""

    def __init__(self, configured_networks: list[str]):
        self._configured_networks = self._parse_networks(configured_networks)
        self._bucket_hits: Counter[str] = Counter()
        self._bucket_kinds: dict[str, str] = {}
        self._unique_ips: set[str] = set()

    @staticmethod
    def _parse_networks(configured_networks: list[str]) -> list[ipaddress._BaseNetwork]:
        parsed: list[ipaddress._BaseNetwork] = []
        for raw in configured_networks:
            try:
                parsed.append(ipaddress.ip_network(raw.strip(), strict=False))
            except ValueError:
                continue

        parsed.sort(key=lambda network: (network.version, network.prefixlen), reverse=True)
        return parsed

    def register_ip(self, ip_str: str) -> str | None:
        if not ip_str:
            return None

        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return None

        normalized_ip = str(ip_obj)
        self._unique_ips.add(normalized_ip)

        bucket, category = self._resolve_bucket(ip_obj)
        bucket_key = str(bucket)
        self._bucket_hits[bucket_key] += 1
        self._bucket_kinds[bucket_key] = category
        return bucket_key

    def _resolve_bucket(self, ip_obj: ipaddress._BaseAddress) -> tuple[ipaddress._BaseNetwork, str]:
        for network in self._configured_networks:
            if network.version == ip_obj.version and ip_obj in network:
                return network, "configured"

        return self._derive_bucket(ip_obj), "observed"

    @staticmethod
    def _derive_bucket(ip_obj: ipaddress._BaseAddress) -> ipaddress._BaseNetwork:
        prefix = 24 if ip_obj.version == 4 else 64
        return ipaddress.ip_network(f"{ip_obj}/{prefix}", strict=False)

    @property
    def unique_ip_count(self) -> int:
        return len(self._unique_ips)

    @property
    def unique_subnet_count(self) -> int:
        return len(self._bucket_hits)

    @property
    def total_observations(self) -> int:
        return sum(self._bucket_hits.values())

    def top_subnets(self, limit: int = 3) -> list[SubnetInsight]:
        total = max(1, self.total_observations)
        return [
            SubnetInsight(
                network=network,
                count=count,
                share_percent=round((count / total) * 100, 1),
                category=self._bucket_kinds.get(network, "observed"),
            )
            for network, count in self._bucket_hits.most_common(limit)
        ]