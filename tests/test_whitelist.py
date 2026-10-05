from squad_vpn import smart, whitelist
from squad_vpn.models import ProxyNode, RankedNode, ValidationResult
from squad_vpn.smart import SmartProfile, select_profile
from squad_vpn.store import NodeStore
from squad_vpn.whitelist import WhitelistIndex

CIDRS = "# comment\n77.88.0.0/18\n77.88.64.0/18\n5.255.255.0/24\n2a02:6b8::/32\n"
DOMAINS = "vk.com\n*.yandex.ru\nimg.avito.st\n"


def _ranked(server, **params):
    return RankedNode(ProxyNode("vless", server, 443, userinfo="u", params=params))


def test_index_matches_subnets_and_domains():
    index = WhitelistIndex.from_text(CIDRS, DOMAINS)
    assert len(index.starts) == 2  # adjacent /18s merged, IPv6 skipped
    assert index.ip_allowed("77.88.100.1") and index.ip_allowed("5.255.255.7")
    assert not index.ip_allowed("8.8.8.8") and not index.ip_allowed("not-an-ip")
    assert index.domain_allowed("vk.com") and index.domain_allowed("api.vk.com")
    assert index.domain_allowed("music.yandex.ru")
    assert not index.domain_allowed("vk.com.evil.org") and not index.domain_allowed("com")
    assert not index.domain_allowed("77.88.1.1")


def test_node_status():
    index = WhitelistIndex.from_text(CIDRS, DOMAINS)
    assert index.status(_ranked("77.88.1.1", sni="vk.com")) == "both"
    assert index.status(_ranked("77.88.1.1", sni="google.com")) == "ip"
    assert index.status(_ranked("1.2.3.4", sni="m.vk.com")) == "sni"
    assert index.status(_ranked("1.2.3.4", host="img.avito.st")) == "sni"
    assert index.status(_ranked("1.2.3.4", sni="google.com")) is None
    index.resolved["srv.example"] = "77.88.5.5"
    assert index.status(_ranked("srv.example")) == "ip"


def test_refresh_lists_downloads_and_keeps_fresh(tmp_path, monkeypatch):
    import httpx

    calls = []

    def handler(request):
        calls.append(str(request.url))
        body = CIDRS * 5 if request.url.path.endswith("cidrwhitelist.txt") else DOMAINS * 5
        return httpx.Response(200, text=body)

    real = httpx.Client
    monkeypatch.setattr(whitelist.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert whitelist.refresh_lists(tmp_path) == "updated"
    assert whitelist.refresh_lists(tmp_path) == "up to date"
    assert len(calls) == 2
    assert whitelist.load_index(tmp_path).ip_allowed("77.88.1.1")


def _seed(store):
    nodes = {
        # Curated, our check failed (servers in Russia often drop foreign probes).
        "curated_dead": ProxyNode("vless", "9.9.9.1", 443, userinfo="a", source="white-src"),
        # Curated, both lists match, but not confirmed by us.
        "curated_both": ProxyNode("vless", "77.88.1.1", 443, userinfo="b", params={"sni": "vk.com"}, source="white-src"),
        # Curated and alive in our check: first.
        "curated_alive": ProxyNode("vless", "9.9.9.2", 443, userinfo="c", source="white-src"),
        # Random node that only happens to sit in a listed subnet: never.
        "random_ip": ProxyNode("vless", "77.88.2.2", 443, userinfo="d", params={"sni": "vk.com"}, source="x"),
        "curated_ru_exit": ProxyNode("vless", "9.9.9.3", 443, userinfo="e", source="white-src"),
    }
    store.upsert_many(list(nodes.values()))
    for key, node in nodes.items():
        alive = key in {"curated_alive", "random_ip", "curated_ru_exit"}
        country = "RU" if key == "curated_ru_exit" else ("DE" if alive else None)
        for _ in range(2):
            store.record_validation(ValidationResult(
                node.fingerprint, alive, latency_ms=50 if alive else None, country=country,
            ))
    return nodes


def test_whitelist_profile_uses_curated_collections_only(tmp_path, monkeypatch):
    lists = tmp_path / "wl"
    lists.mkdir()
    (lists / "cidr.txt").write_text(CIDRS, encoding="utf-8")
    (lists / "domains.txt").write_text(DOMAINS, encoding="utf-8")
    monkeypatch.setattr(whitelist.load_index, "__defaults__", (lists,))
    monkeypatch.setattr(smart, "sources_with_tags", lambda tags, path=None: {"white-src"})
    store = NodeStore(tmp_path / "db.sqlite3")
    try:
        _seed(store)
        profile = SmartProfile(
            "whitelist", whitelist=True, require_alive=False, seen_within_hours=3,
            exclude_countries=("RU",), max_asn_share=None,
        )
        hosts = [item.node.host for item in select_profile(store, profile)]
    finally:
        store.close()
    assert hosts == ["9.9.9.2", "77.88.1.1", "9.9.9.1"]


def test_speed_sort_min_speed_and_prefer_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(smart, "sources_with_tags", lambda tags, path=None: {"ru-src"})
    store = NodeStore(tmp_path / "db.sqlite3")
    try:
        nodes = [
            ProxyNode("trojan", f"h{i}.example", 443, userinfo=str(i), source="ru-src" if i == 3 else "x")
            for i in range(4)
        ]
        store.upsert_many(nodes)
        for node, speed in zip(nodes, (900.0, 8000.0, None, 3000.0), strict=True):
            for _ in range(2):
                store.record_validation(ValidationResult(node.fingerprint, True, latency_ms=50, speed_kbps=speed))
        fast = SmartProfile("fast", sort_by="speed", min_speed_kbps=1000, max_asn_share=None)
        assert [i.node.host for i in select_profile(store, fast)] == ["h1.example", "h3.example", "h2.example"]
        tagged = SmartProfile("top", prefer_tags=("ru-checked",), max_asn_share=None)
        assert select_profile(store, tagged)[0].node.host == "h3.example"
        assert store.get_ranked(nodes[1].fingerprint).speed_kbps == 8000.0
    finally:
        store.close()


def test_speed_is_smoothed(tmp_path):
    store = NodeStore(tmp_path / "db.sqlite3")
    try:
        node = ProxyNode("trojan", "h.example", 443, userinfo="pw")
        store.upsert_many([node])
        store.record_validation(ValidationResult(node.fingerprint, True, latency_ms=50, speed_kbps=1000.0))
        store.record_validation(ValidationResult(node.fingerprint, True, latency_ms=50, speed_kbps=2000.0))
        store.record_validation(ValidationResult(node.fingerprint, False, error="down"))
        assert store.get_ranked(node.fingerprint).speed_kbps == 1600.0
    finally:
        store.close()


def test_sources_with_tags_matches_how_nodes_store_their_source(tmp_path):
    from squad_vpn.collector import collect_source_specs  # noqa: F401  (source format)
    from squad_vpn.smart import sources_with_tags

    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - name: white\n    url: https://example.com/white.txt\n    tags: [whitelist]\n"
        "  - name: other\n    url: https://example.com/other.txt\n",
        encoding="utf-8",
    )
    found = sources_with_tags(("whitelist",), path)
    assert "https://example.com/white.txt" in found and "white" in found
    assert "https://example.com/other.txt" not in found
