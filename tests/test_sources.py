from squad_vpn.sources import SourceReport, SourceSpec, load_source_specs
from squad_vpn.store import NodeStore


def test_yaml_source_registry_filters_disabled_and_sorts(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - name: later\n    url: https://b.example/sub\n    priority: 20\n"
        "  - name: first\n    url: https://a.example/sub\n    priority: 10\n"
        "  - name: off\n    url: https://off.example/sub\n    enabled: false\n",
        encoding="utf-8",
    )
    specs = load_source_specs(path)
    assert [item.name for item in specs] == ["first", "later"]


def test_source_report_is_persisted(tmp_path):
    store = NodeStore(tmp_path / "sources.sqlite3")
    try:
        spec = SourceSpec("demo", "https://example.com/sub", tags=("test",))
        store.record_source_report(
            SourceReport(spec, True, nodes_found=20, nodes_selected=10, duration_ms=42)
        )
        row = store.list_source_status()[0]
        assert row["name"] == "demo"
        assert row["success_count"] == 1
        assert row["nodes_selected"] == 10
    finally:
        store.close()


def test_source_limit_spreads_across_feed():
    from squad_vpn.collector import _spread_limit
    from squad_vpn.models import ProxyNode

    nodes = [ProxyNode("vless", f"host{i}", 443) for i in range(100)]
    selected = _spread_limit(nodes, 4)
    assert [node.host for node in selected] == ["host0", "host25", "host50", "host75"]


def test_removed_sources_are_pruned(tmp_path):
    store = NodeStore(tmp_path / "prune.sqlite3")
    try:
        for name in ("keep", "drop"):
            store.record_source_report(SourceReport(SourceSpec(name, f"https://{name}.example"), True))
        store.prune_sources(["keep"])
        assert [row["name"] for row in store.list_source_status()] == ["keep"]
    finally:
        store.close()
