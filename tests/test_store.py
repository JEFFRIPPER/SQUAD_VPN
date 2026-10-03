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


def _age(store, fingerprint, column, hours):
    store.connection.execute(
        f"UPDATE nodes SET {column} = datetime('now', ?) WHERE fingerprint = ?",
        (f"-{hours} hours", fingerprint),
    )
    store.connection.commit()


def test_validation_candidates_do_not_starve_rechecks(tmp_path):
    from squad_vpn.models import ValidationResult

    store = NodeStore(tmp_path / "budget.sqlite3")
    try:
        old = ProxyNode("vless", "old.example", 443, raw_uri="old")
        new_nodes = [ProxyNode("vless", f"new{i}.example", 443, raw_uri=f"n{i}") for i in range(10)]
        store.upsert_many([old, *new_nodes])
        store.record_validation(ValidationResult(old.fingerprint, True, latency_ms=90))
        _age(store, old.fingerprint, "last_checked", 2)

        picked = store.list_validation_candidates(recheck_after_minutes=60, limit=4)
        fingerprints = [node.fingerprint for node in picked]
        assert len(picked) == 4
        assert old.fingerprint in fingerprints
    finally:
        store.close()


def test_validation_candidates_fill_unused_quota(tmp_path):
    store = NodeStore(tmp_path / "fill.sqlite3")
    try:
        nodes = [ProxyNode("vless", f"n{i}.example", 443, raw_uri=f"n{i}") for i in range(6)]
        store.upsert_many(nodes)
        assert len(store.list_validation_candidates(limit=5)) == 5
    finally:
        store.close()


def test_validation_candidates_skip_nodes_gone_from_sources(tmp_path):
    store = NodeStore(tmp_path / "gone.sqlite3")
    try:
        gone = ProxyNode("vless", "gone.example", 443, raw_uri="gone")
        live = ProxyNode("vless", "live.example", 443, raw_uri="live")
        store.upsert_many([gone, live])
        _age(store, gone.fingerprint, "last_seen", 100)
        picked = {n.fingerprint for n in store.list_validation_candidates(seen_within_hours=72)}
        assert picked == {live.fingerprint}
    finally:
        store.close()


def test_history_is_pruned_but_counters_keep_growing(tmp_path):
    from squad_vpn import store as store_module
    from squad_vpn.models import ValidationResult

    store = NodeStore(tmp_path / "prune.sqlite3")
    try:
        node = ProxyNode("trojan", "p.example", 443, userinfo="x", raw_uri="t")
        store.upsert_many([node])
        total = store_module.HISTORY_KEEP + 15
        for i in range(total):
            store.record_validation(ValidationResult(node.fingerprint, i % 3 != 0, latency_ms=100))
        rows = store.connection.execute(
            "SELECT COUNT(*) FROM health_checks WHERE fingerprint = ?", (node.fingerprint,)
        ).fetchone()[0]
        assert rows == store_module.HISTORY_KEEP
        ranked = store.list_ranked()[0]
        assert ranked.attempts == total
    finally:
        store.close()


def test_v02_database_backfills_stability(tmp_path):
    import sqlite3

    database = tmp_path / "v02.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE nodes (
            fingerprint TEXT PRIMARY KEY, protocol TEXT NOT NULL,
            host TEXT NOT NULL, port INTEGER NOT NULL,
            userinfo TEXT NOT NULL DEFAULT '', params_json TEXT NOT NULL DEFAULT '{}',
            name TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
            raw_uri TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            alive INTEGER, latency_ms REAL, quality_score REAL NOT NULL DEFAULT 0,
            last_checked TEXT, exit_ip TEXT, country TEXT, asn TEXT, validation_error TEXT,
            success_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
            checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, alive INTEGER NOT NULL,
            latency_ms REAL, exit_ip TEXT, country TEXT, asn TEXT, error TEXT
        );
        INSERT INTO nodes (fingerprint, protocol, host, port, alive, latency_ms,
            quality_score, last_checked, success_count, failure_count)
        VALUES ('fp', 'vless', 'h', 443, 1, 100, 80, CURRENT_TIMESTAMP, 3, 0);
        INSERT INTO health_checks (fingerprint, alive, latency_ms) VALUES
            ('fp', 1, 90), ('fp', 1, 100), ('fp', 1, 110);
        """
    )
    connection.commit()
    connection.close()

    store = NodeStore(database)
    try:
        ranked = store.list_ranked(alive_only=True, min_stability=50)
        assert len(ranked) == 1
        assert ranked[0].stability_score > 50
        assert ranked[0].recent_success_rate == 1.0
    finally:
        store.close()
