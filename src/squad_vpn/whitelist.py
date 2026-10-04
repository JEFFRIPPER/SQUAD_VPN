"""Russian mobile "white lists": what stays reachable when the internet is cut.

During restrictions mobile operators let through only approved IP subnets
(Yandex, VK, big Russian services) and, in milder regions, approved domain
names (SNI). A VPN node works then only if its server sits in such a subnet
or disguises itself with such a domain — and its exit is abroad, otherwise
Telegram, Discord and YouTube stay blocked.

The lists are community-maintained (hxehex/russia-mobile-internet-whitelist)
and refreshed by the cycle; nothing here is hard-coded.
"""

from __future__ import annotations

import bisect
import ipaddress
import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import __version__
from .models import RankedNode


WHITELIST_DIR = Path("data/whitelist")
CIDR_URL = "https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/main/cidrwhitelist.txt"
DOMAINS_URL = "https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/main/whitelist.txt"
REFRESH_SECONDS = 12 * 3600
SNI_KEYS = ("sni", "servername", "serverName", "peer", "host")

log = logging.getLogger("squad_vpn.whitelist")


def _lines(text: str) -> list[str]:
    return [
        line.split("#", 1)[0].strip().lower()
        for line in text.splitlines()
        if line.split("#", 1)[0].strip()
    ]


@dataclass(slots=True)
class WhitelistIndex:
    """IPv4 ranges and domain names that stay reachable under restrictions."""

    starts: list[int] = field(default_factory=list)
    ends: list[int] = field(default_factory=list)
    domains: frozenset[str] = frozenset()
    resolved: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def from_text(cls, cidrs: str, domains: str) -> "WhitelistIndex":
        ranges = []
        for line in _lines(cidrs):
            try:
                network = ipaddress.ip_network(line, strict=False)
            except ValueError:
                continue
            if network.version == 4:
                ranges.append((int(network.network_address), int(network.broadcast_address)))
        ranges.sort()
        merged: list[tuple[int, int]] = []
        for start, end in ranges:
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return cls(
            starts=[s for s, _ in merged],
            ends=[e for _, e in merged],
            domains=frozenset(line.lstrip("*.") for line in _lines(domains)),
        )

    @property
    def empty(self) -> bool:
        return not self.starts and not self.domains

    def ip_allowed(self, address: str | None) -> bool:
        try:
            value = int(ipaddress.IPv4Address(address or ""))
        except ValueError:
            return False
        index = bisect.bisect_right(self.starts, value) - 1
        return index >= 0 and value <= self.ends[index]

    def domain_allowed(self, name: str | None) -> bool:
        name = (name or "").strip().lower().rstrip(".")
        if not name or name.replace(".", "").isdigit():
            return False
        parts = name.split(".")
        return any(".".join(parts[i:]) in self.domains for i in range(len(parts) - 1))

    def server_ip(self, host: str) -> str | None:
        try:
            ipaddress.IPv4Address(host)
            return host
        except ValueError:
            return self.resolved.get(host.lower())

    def status(self, item: RankedNode) -> str | None:
        """"ip" (server in a white subnet), "sni" (white domain), "both" or None."""
        node = item.node
        ip_ok = self.ip_allowed(self.server_ip(node.host))
        names = [node.params.get(key) for key in SNI_KEYS]
        sni_ok = any(self.domain_allowed(name) for name in names if name)
        if ip_ok and sni_ok:
            return "both"
        return "ip" if ip_ok else "sni" if sni_ok else None

    def resolve(self, hosts: set[str], *, workers: int = 32) -> None:
        """Resolve domain hosts to IPv4 (the subnet check needs addresses)."""
        pending = []
        for host in hosts:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if host.lower() not in self.resolved:
                    pending.append(host.lower())
        if not pending:
            return

        def lookup(host: str) -> tuple[str, str | None]:
            try:
                info = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
                return host, str(info[0][4][0])
            except (OSError, UnicodeError, IndexError):
                return host, None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            self.resolved.update(pool.map(lookup, pending))


def refresh_lists(directory: Path = WHITELIST_DIR, *, force: bool = False, timeout: float = 60.0) -> str:
    """Download the lists when they are missing or older than 12 hours."""
    directory.mkdir(parents=True, exist_ok=True)
    targets = {"cidr.txt": CIDR_URL, "domains.txt": DOMAINS_URL}
    fresh = all(
        (directory / name).exists()
        and time.time() - (directory / name).stat().st_mtime < REFRESH_SECONDS
        for name in targets
    )
    if fresh and not force:
        return "up to date"
    headers = {"User-Agent": f"SQUAD-VPN/{__version__}"}
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False, headers=headers) as client:
        for name, url in targets.items():
            response = client.get(url)
            response.raise_for_status()
            text = response.text
            if len(_lines(text)) < 10:
                raise ValueError(f"{url}: список подозрительно пуст")
            partial = directory / (name + ".part")
            partial.write_text(text, encoding="utf-8")
            partial.replace(directory / name)
    return "updated"


_CACHE: dict[Path, tuple[float, WhitelistIndex]] = {}


def load_index(directory: Path = WHITELIST_DIR) -> WhitelistIndex:
    """The cached index; empty when the lists were never downloaded."""
    cidr, domains = directory / "cidr.txt", directory / "domains.txt"
    try:
        stamp = max(cidr.stat().st_mtime, domains.stat().st_mtime)
    except OSError:
        return WhitelistIndex()
    cached = _CACHE.get(directory)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    index = WhitelistIndex.from_text(
        cidr.read_text(encoding="utf-8"), domains.read_text(encoding="utf-8")
    )
    _CACHE[directory] = (stamp, index)
    return index
