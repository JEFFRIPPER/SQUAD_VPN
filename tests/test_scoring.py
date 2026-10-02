from squad_vpn.scoring import HealthStats, quality_score


def test_quality_score_rewards_reliability_and_speed():
    good = HealthStats(attempts=10, successes=10, failures=0, latency_ms=80)
    bad = HealthStats(attempts=10, successes=5, failures=5, latency_ms=900)
    assert quality_score(good, alive=True) > quality_score(bad, alive=True)
    assert quality_score(good, alive=True) > 90


def test_dead_node_is_penalized():
    stats = HealthStats(attempts=10, successes=9, failures=1, latency_ms=100)
    assert quality_score(stats, alive=False) < quality_score(stats, alive=True)
