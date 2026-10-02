from squad_vpn.scoring import HealthStats, quality_score


def test_quality_score_rewards_reliability_and_speed():
    good = HealthStats(attempts=10, successes=10, failures=0, latency_ms=80)
    bad = HealthStats(attempts=10, successes=5, failures=5, latency_ms=900)
    assert quality_score(good, alive=True) > quality_score(bad, alive=True)
    assert quality_score(good, alive=True) > 90


def test_dead_node_is_penalized():
    stats = HealthStats(attempts=10, successes=9, failures=1, latency_ms=100)
    assert quality_score(stats, alive=False) < quality_score(stats, alive=True)


def test_lower_jitter_scores_higher():
    stable = HealthStats(
        attempts=8, successes=8, failures=0, latency_ms=120,
        jitter_ms=10, recent_success_rate=1.0,
    )
    noisy = HealthStats(
        attempts=8, successes=8, failures=0, latency_ms=120,
        jitter_ms=300, recent_success_rate=1.0,
    )
    assert quality_score(stable, alive=True) > quality_score(noisy, alive=True)
