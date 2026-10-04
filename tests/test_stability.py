import asyncio

from squad_vpn.models import ProxyNode, RankedNode, ValidationResult
from squad_vpn.smart import SmartProfile, is_masked, select_profile
from squad_vpn.store import NodeStore
from squad_vpn.validator import MihomoValidator


def _ranked(protocol, **params):
    return RankedNode(ProxyNode(protocol, "h.example", 443, userinfo="u", params=params))


def test_masked_transports():
    assert is_masked(_ranked("vless", security="reality"))
    assert is_masked(_ranked("vless", security="tls"))
    assert not is_masked(_ranked("vless"))
    assert not is_masked(_ranked("vless", security="none"))
    assert is_masked(_ranked("trojan"))
    assert not is_masked(_ranked("trojan", security="none"))
    assert is_masked(_ranked("vmess", tls="tls"))
    assert not is_masked(_ranked("vmess"))
    assert is_masked(_ranked("hysteria2"))
    assert not is_masked(_ranked("ss"))


def _nodes(count):
    return [ProxyNode("trojan", f"h{i}.example", 443, userinfo="pw") for i in range(count)]


def test_download_failure_marks_node_dead(monkeypatch):
    nodes = _nodes(6)
    validator = MihomoValidator("missing", download_bytes=1000)
    results = [ValidationResult(n.fingerprint, True, latency_ms=50) for n in nodes]
    results[5].alive = False

    async def fake_download(batch, concurrency):
        assert nodes[5] not in batch  # dead nodes are not downloaded through
        return {
            n.fingerprint: ("зависло на 15 КБ", None) if n is nodes[1] else (None, 4200.0)
            for n in batch
        }

    monkeypatch.setattr(validator, "_run_download", fake_download)
    asyncio.run(validator._download_batch(nodes, results, 4))
    assert [r.alive for r in results] == [True, False, True, True, True, False]
    assert "15 КБ" in results[1].error
    assert results[0].speed_kbps == 4200.0 and results[1].speed_kbps is None


def test_download_site_down_keeps_ping_verdict(monkeypatch):
    nodes = _nodes(6)
    validator = MihomoValidator("missing", download_bytes=1000)
    results = [ValidationResult(n.fingerprint, True, latency_ms=50) for n in nodes]

    async def all_fail(batch, concurrency):
        return {n.fingerprint: ("ConnectError на 0 КБ", None) for n in batch}

    monkeypatch.setattr(validator, "_run_download", all_fail)
    asyncio.run(validator._download_batch(nodes, results, 4))
    assert all(r.alive for r in results)


def test_download_disabled_by_default(monkeypatch):
    validator = MihomoValidator("missing")
    nodes = _nodes(2)

    async def fake_probe(batch, concurrency):
        return [ValidationResult(n.fingerprint, True, latency_ms=10) for n in batch]

    async def boom(*args, **kwargs):
        raise AssertionError("download must not run")

    monkeypatch.setattr(validator, "_run_probe", fake_probe)
    monkeypatch.setattr(validator, "_download_batch", boom)
    assert all(r.alive for r in asyncio.run(validator.validate(nodes)))


def test_top_profile_filters_and_orders(tmp_path):
    store = NodeStore(tmp_path / "db.sqlite3")
    try:
        plain = ProxyNode("ss", "ss.example", 8388, userinfo="aes-128-gcm:pw")
        once = ProxyNode("vless", "once.example", 443, userinfo="u", params={"security": "reality"})
        hetzner = ProxyNode("vless", "hz.example", 443, userinfo="u", params={"security": "reality"})
        good = ProxyNode("trojan", "good.example", 443, userinfo="pw")
        store.upsert_many([plain, once, hetzner, good])
        for node, checks, latency, asn in (
            (plain, 5, 50, "AS1 Plain"),
            (once, 1, 40, "AS2 Once"),
            (hetzner, 5, 30, "AS24940 Hetzner"),
            (good, 5, 90, "AS3 Good"),
        ):
            for _ in range(checks):
                store.record_validation(
                    ValidationResult(node.fingerprint, True, latency_ms=latency, asn=asn)
                )
        profile = SmartProfile(
            "top", min_checks=4, require_tls=True, limit=10,
            deprioritize_asns=("AS24940",), max_asn_share=None,
        )
        hosts = [item.node.host for item in select_profile(store, profile)]
    finally:
        store.close()
    # ss is not masked, "once" has too few checks, Hetzner goes last.
    assert hosts == ["good.example", "hz.example"]
