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
