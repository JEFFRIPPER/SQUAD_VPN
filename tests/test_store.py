from squad_vpn.models import ProxyNode
from squad_vpn.store import NodeStore


def test_store_upsert_and_list(tmp_path):
    database = tmp_path / "nodes.sqlite3"
    store = NodeStore(database)
    try:
        node = ProxyNode(
            protocol="vless",
            host="example.com",
            port=443,
            userinfo="11111111-1111-1111-1111-111111111111",
            params={"security": "tls"},
            name="First",
            source="test",
            raw_uri="test-uri",
        )
        assert store.upsert_many([node]) == 1
        assert store.count() == 1
        loaded = store.list_nodes()
        assert len(loaded) == 1
        assert loaded[0].fingerprint == node.fingerprint
    finally:
        store.close()


def test_store_records_validation_and_ranking(tmp_path):
    from squad_vpn.models import ValidationResult

    database = tmp_path / "health.sqlite3"
    store = NodeStore(database)
    try:
        node = ProxyNode(
            protocol="trojan",
            host="example.com",
            port=443,
            userinfo="secret",
            raw_uri="trojan://secret@example.com:443",
        )
        store.upsert_many([node])
        score = store.record_validation(
            ValidationResult(node.fingerprint, True, latency_ms=120, country="DE")
        )
        ranked = store.list_ranked(alive_only=True)
        assert score > 0
        assert len(ranked) == 1
        assert ranked[0].alive is True
        assert ranked[0].latency_ms == 120
        assert ranked[0].country == "DE"
        assert ranked[0].success_count == 1
    finally:
        store.close()


def test_v01_database_migrates_without_delete(tmp_path):
    import sqlite3

    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE nodes (
            fingerprint TEXT PRIMARY KEY, protocol TEXT NOT NULL,
            host TEXT NOT NULL, port INTEGER NOT NULL,
            userinfo TEXT NOT NULL DEFAULT '', params_json TEXT NOT NULL DEFAULT '{}',
            name TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
            raw_uri TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()
    connection.close()

    store = NodeStore(database)
    try:
        columns = {row["name"] for row in store.connection.execute("PRAGMA table_info(nodes)")}
        assert "quality_score" in columns
        assert "success_count" in columns
        assert store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='health_checks'"
        ).fetchone() is not None
    finally:
        store.close()


def test_recent_history_calculates_jitter_and_stability(tmp_path):
    from squad_vpn.models import ValidationResult

    store = NodeStore(tmp_path / "jitter.sqlite3")
    try:
        node = ProxyNode(
            protocol="vless", host="stable.example", port=443,
            userinfo="11111111-1111-1111-1111-111111111111",
            raw_uri="vless://example",
        )
        store.upsert_many([node])
        for latency in (100, 120, 80):
            store.record_validation(
                ValidationResult(node.fingerprint, True, latency_ms=latency)
            )
        ranked = store.list_ranked(alive_only=True)
        assert len(ranked) == 1
        assert ranked[0].jitter_ms is not None
        assert ranked[0].jitter_ms > 0
        assert ranked[0].recent_success_rate == 1.0
        assert ranked[0].stability_score > 70
    finally:
        store.close()


def test_validation_candidates_skip_recently_checked_nodes(tmp_path):
    from squad_vpn.models import ValidationResult

    store = NodeStore(tmp_path / "candidates.sqlite3")
    try:
        checked = ProxyNode("vless", "checked.example", 443, raw_uri="a")
        fresh = ProxyNode("vless", "fresh.example", 443, raw_uri="b")
        store.upsert_many([checked, fresh])
        store.record_validation(
            ValidationResult(checked.fingerprint, True, latency_ms=100)
        )
        candidates = store.list_validation_candidates(recheck_after_minutes=60)
        fingerprints = {node.fingerprint for node in candidates}
        assert fresh.fingerprint in fingerprints
        assert checked.fingerprint not in fingerprints
    finally:
        store.close()
