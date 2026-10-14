from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlencode


@dataclass(slots=True)
class ProxyNode:
    protocol: str
    host: str
    port: int
    userinfo: str = ""
    params: dict[str, str] = field(default_factory=dict)
    name: str = ""
    source: str = ""
    raw_uri: str = ""

    def canonical_items(self) -> list[tuple[str, str]]:
        ignored = {"name", "remark", "remarks", "ps"}
        return sorted(
            (str(k).lower(), str(v))
            for k, v in self.params.items()
            if str(k).lower() not in ignored
        )

    def canonical_string(self) -> str:
        params = urlencode(self.canonical_items(), doseq=True)
        return "|".join(
            [self.protocol.lower(), self.host.lower(), str(self.port), self.userinfo, params]
        )

    @property
    def fingerprint(self) -> str:
        return sha256(self.canonical_string().encode("utf-8")).hexdigest()

    def display_name(self) -> str:
        return self.name or f"{self.protocol.upper()} {self.host}:{self.port}"


@dataclass(slots=True)
class ValidationResult:
    fingerprint: str
    alive: bool
    latency_ms: float | None = None
    exit_ip: str | None = None
    country: str | None = None
    asn: str | None = None
    error: str | None = None
    probe_id: str = "local"
    # Throughput of the download check, kbit/s (None when not measured).
    speed_kbps: float | None = None


@dataclass(slots=True)
class RankedNode:
    node: ProxyNode
    alive: bool | None = None
    latency_ms: float | None = None
    jitter_ms: float | None = None
    recent_success_rate: float = 0.0
    stability_score: float = 0.0
    quality_score: float = 0.0
    last_checked: str | None = None
    last_seen: str | None = None
    exit_ip: str | None = None
    country: str | None = None
    asn: str | None = None
    success_count: int = 0
    failure_count: int = 0
    validation_error: str | None = None
    speed_kbps: float | None = None
    # Region code -> {"alive", "latency_ms", "checked_at", "probes"} from probes.
    regions: dict[str, dict[str, object]] = field(default_factory=dict)
    # Alive by our checks without a break since then (two failures in a row reset it).
    alive_since: str | None = None
    first_seen: str | None = None

    @property
    def alive_hours(self) -> float:
        """How long the node has kept working: long-lived servers tend to stay."""
        return _hours_since(self.alive_since) if self.alive else 0.0

    @property
    def listed_hours(self) -> float:
        """How long the node has been published by its sources."""
        return _hours_since(self.first_seen)

    def region_status(self, region: str) -> str:
        """ok | blocked | down | unknown for one probe region (e.g. "RU").

        blocked = probes in this region fail while another region sees the
        node alive, i.e. the node works but not from there.
        """
        here = self.regions.get(region.upper())
        if here is None:
            return "unknown"
        if here["alive"]:
            return "ok"
        elsewhere = any(
            info["alive"] for code, info in self.regions.items() if code != region.upper()
        )
        return "blocked" if elsewhere else "down"

    @property
    def attempts(self) -> int:
        return self.success_count + self.failure_count


def _hours_since(stamp: str | None) -> float:
    """Hours from an SQLite CURRENT_TIMESTAMP (UTC) until now; 0 when unknown."""
    if not stamp:
        return 0.0
    try:
        then = datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 3600.0)
