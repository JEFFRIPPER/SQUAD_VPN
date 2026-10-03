from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class HealthStats:
    attempts: int
    successes: int
    failures: int
    latency_ms: float | None
    jitter_ms: float | None = None
    recent_success_rate: float | None = None

    @property
    def success_rate(self) -> float:
        if self.attempts <= 0:
            return 0.0
        return self.successes / self.attempts


RECENT_DECAY = 0.75


def weighted_success_rate(outcomes: list[bool], decay: float = RECENT_DECAY) -> float:
    """Success rate where newer checks weigh more (``outcomes`` newest first).

    With decay 0.75 the latest check weighs ~4x the fifth one, so a node that
    just went down drops fast, and one that recovered climbs back quickly.
    """
    if not outcomes:
        return 0.0
    weights = [decay**index for index in range(len(outcomes))]
    hits = sum(weight for weight, ok in zip(weights, outcomes) if ok)
    return hits / sum(weights)


def representative_latency(latencies: list[float]) -> float | None:
    """Median of recent successful probes: robust to a single slow spike."""
    if not latencies:
        return None
    ordered = sorted(latencies)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def latency_score(latency_ms: float | None) -> float:
    if latency_ms is None or latency_ms <= 0:
        return 0.0
    return max(0.0, 1.0 - min(latency_ms, 2000.0) / 2000.0)


def jitter_score(jitter_ms: float | None) -> float:
    if jitter_ms is None:
        return 0.5
    if jitter_ms <= 0:
        return 1.0
    return max(0.0, 1.0 - min(jitter_ms, 400.0) / 400.0)


def confidence_score(attempts: int) -> float:
    if attempts <= 0:
        return 0.0
    return min(1.0, attempts / 8.0)


def stability_score(stats: HealthStats) -> float:
    reliability = (
        stats.recent_success_rate
        if stats.recent_success_rate is not None
        else stats.success_rate
    )
    raw = (0.75 * reliability) + (0.25 * jitter_score(stats.jitter_ms))
    confidence = 0.7 + (0.3 * confidence_score(stats.attempts))
    return round(max(0.0, min(1.0, raw * confidence)) * 100.0, 2)


def quality_score(stats: HealthStats, alive: bool | None = None) -> float:
    if stats.attempts <= 0:
        return 0.0
    reliability = (
        stats.recent_success_rate
        if stats.recent_success_rate is not None
        else stats.success_rate
    )
    base = (
        (0.50 * reliability)
        + (0.25 * latency_score(stats.latency_ms))
        + (0.15 * jitter_score(stats.jitter_ms))
        + (0.10 * confidence_score(stats.attempts))
    )
    if alive is False:
        base *= 0.30
    return round(max(0.0, min(1.0, base)) * 100.0, 2)
