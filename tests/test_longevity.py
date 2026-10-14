from squad_vpn.models import ProxyNode, ValidationResult
from squad_vpn.smart import SmartProfile, select_profile
from squad_vpn.store import NodeStore


def _node(host: str) -> ProxyNode:
    return ProxyNode(protocol="trojan", host=host, port=443, userinfo="s", raw_uri=f"trojan://s@{host}:443")


def _check(store: NodeStore, node: ProxyNode, alive: bool) -> None:
    store.record_validation(ValidationResult(node.fingerprint, alive, latency_ms=90 if alive else None, country="DE"))


def _since(store: NodeStore, node: ProxyNode) -> str | None:
    return store.get_ranked(node.fingerprint).alive_since


def test_alive_since_survives_one_miss_and_resets_after_two(tmp_path):
    store = NodeStore(tmp_path / "l.sqlite3")
    try:
        node = _node("a.example")
        store.upsert_many([node])
        _check(store, node, True)
        started = _since(store, node)
        assert started is not None
        # One failed check (our network, a hiccup) keeps the streak.
        _check(store, node, False)
        assert _since(store, node) == started
        _check(store, node, True)
        assert _since(store, node) == started
        # Two in a row: the server really went down, the count starts over.
        _check(store, node, False)
        _check(store, node, False)
        assert _since(store, node) is None
    finally:
        store.close()


def test_long_lived_nodes_go_first_and_min_alive_hours_filters(tmp_path):
    store = NodeStore(tmp_path / "l.sqlite3")
    try:
        young, old = _node("young.example"), _node("old.example")
        store.upsert_many([young, old])
        for node in (young, old):
            for _ in range(3):
                _check(store, node, True)
        # The young one is faster, but the old one has worked for two days.
        store.connection.execute(
            "UPDATE nodes SET alive_since = datetime('now', '-48 hours') WHERE fingerprint = ?",
            (old.fingerprint,),
        )
        store.connection.execute(
            "UPDATE nodes SET quality_score = quality_score + 5 WHERE fingerprint = ?",
            (young.fingerprint,),
        )
        store.connection.commit()
        base = dict(name="t", per_exit_ip=None, max_asn_share=None)
        plain = [i.node.host for i in select_profile(store, SmartProfile(**base))]
        assert plain == ["young.example", "old.example"]
        ranked = [i.node.host for i in select_profile(store, SmartProfile(**base, long_lived_hours=24))]
        assert ranked == ["old.example", "young.example"]
        kept = [i.node.host for i in select_profile(store, SmartProfile(**base, min_alive_hours=12))]
        assert kept == ["old.example"]
    finally:
        store.close()
