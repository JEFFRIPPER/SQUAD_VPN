from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class HealthStats:
    attempts: int
    successes: int
    failures: int
    latency_ms: float | None

    @property
    def success_rate(self) -> float:
        if self.attempts <= 0:
            return 0.0
        return self.successes / self.attempts


def latency_score(latency_ms: float | None) -> float:
    """0..1: fast nodes score higher, >=2000 ms scores zero."""
    if latency_ms is None or latency_ms <= 0:
        return 0.0
    return max(0.0, 1.0 - min(latency_ms, 2000.0) / 2000.0)


def confidence_score(attempts: int) -> float:
    """Avoid ranking a node as perfect after only one successful probe."""
    if attempts <= 0:
        return 0.0
    return min(1.0, attempts / 10.0)


def quality_score(stats: HealthStats, alive: bool | None = None) -> float:
    """Return a stable 0..100 score for ranking subscription nodes."""
    if stats.attempts <= 0:
        return 0.0

    reliability = stats.success_rate
    speed = latency_score(stats.latency_ms)
    confidence = confidence_score(stats.attempts)
    base = (0.65 * reliability) + (0.30 * speed) + (0.05 * confidence)
    if alive is False:
        base *= 0.35
    return round(max(0.0, min(1.0, base)) * 100.0, 2)
