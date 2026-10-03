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


def test_smart_catalog_removes_stale_and_sanitizes(tmp_path):
    store = NodeStore(tmp_path / "stale.sqlite3")
    try:
        node = ProxyNode("trojan", "a.example", 443, userinfo="s", raw_uri="trojan://s@a.example:443")
        store.upsert_many([node])
        store.record_validation(
            ValidationResult(node.fingerprint, True, latency_ms=80, country="../de")
        )
        out = tmp_path / "out"
        stale = out / "country" / "NL"
        stale.parent.mkdir(parents=True)
        stale.write_text("dead\n", encoding="utf-8")
        (out / "country" / "NL.yaml").write_text("proxies: []\n", encoding="utf-8")

        index = export_smart_catalog(store, out)
        assert list(index["countries"]) == ["DE"]
        assert sorted(p.name for p in (out / "country").iterdir()) == ["DE", "DE.yaml"]
        assert not (tmp_path / "de").exists()
    finally:
        store.close()


def test_protocol_export_removes_stale_files(tmp_path):
    from squad_vpn.exporter import export_by_protocol

    folder = tmp_path / "protocols"
    folder.mkdir()
    (folder / "vmess").write_text("old\n", encoding="utf-8")
    export_by_protocol([ProxyNode("vless", "h", 443, raw_uri="vless://x@h:443")], folder)
    assert sorted(p.name for p in folder.iterdir()) == ["vless"]
