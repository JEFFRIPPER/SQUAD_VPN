from squad_vpn.models import ProxyNode, ValidationResult
from squad_vpn.smart import export_smart_catalog
from squad_vpn.store import NodeStore


def test_smart_catalog_exports_fast_and_balanced(tmp_path):
    store = NodeStore(tmp_path / "smart.sqlite3")
    try:
        node = ProxyNode(
            protocol="trojan",
            host="fast.example",
            port=443,
            userinfo="secret",
            raw_uri="trojan://secret@fast.example:443",
        )
        store.upsert_many([node])
        for latency in (80, 90, 85):
            store.record_validation(
                ValidationResult(node.fingerprint, True, latency_ms=latency, country="DE")
            )
        index = export_smart_catalog(store, tmp_path / "out")
        assert index["profiles"]["balanced"]["count"] == 1
        assert index["profiles"]["fast"]["count"] == 1
        assert index["countries"]["DE"]["count"] == 1
        assert (tmp_path / "out" / "fast.yaml").exists()
    finally:
        store.close()
