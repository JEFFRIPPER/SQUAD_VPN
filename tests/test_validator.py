import asyncio

from squad_vpn.models import ProxyNode, ValidationResult
from squad_vpn.validator import MihomoStartError, MihomoValidator


def _nodes(count):
    return [ProxyNode("trojan", f"h{i}.example", 443, userinfo="pw") for i in range(count)]


def test_bad_node_is_isolated_by_bisection(monkeypatch):
    nodes = _nodes(5)
    bad = nodes[3].fingerprint
    validator = MihomoValidator("missing")

    async def fake_probe(batch, concurrency):
        if any(node.fingerprint == bad for node in batch):
            raise MihomoStartError("proxy rejected")
        return [ValidationResult(node.fingerprint, True, latency_ms=50) for node in batch]

    monkeypatch.setattr(validator, "_run_probe", fake_probe)
    results = asyncio.run(validator.validate(nodes))
    assert [r.fingerprint for r in results] == [n.fingerprint for n in nodes]
    assert [r.alive for r in results] == [True, True, True, False, True]
    assert "Mihomo" in results[3].error


def test_unconvertible_nodes_get_a_failed_result(monkeypatch, tmp_path):
    from squad_vpn import validator as module

    nodes = [ProxyNode("ss", "h.example", 443, userinfo="no-colon"), *_nodes(1)]
    binary = tmp_path / "mihomo.exe"
    binary.write_text("", encoding="utf-8")
    validator = MihomoValidator(binary)

    class FakeProcess:
        def poll(self):
            return 0

    def fake_start(self, batch, directory, controller_port, mixed_port):
        from squad_vpn.mihomo import build_runtime_config

        _, converted = build_runtime_config(batch, controller_port=1, mixed_port=2)
        return FakeProcess(), converted

    async def fake_ready(self, process, base_url, log_path, timeout=12.0):
        return None

    async def fake_probe_one(self, client, item, semaphore):
        return ValidationResult(item.fingerprint, True, latency_ms=10)

    monkeypatch.setattr(module.MihomoValidator, "_start", fake_start)
    monkeypatch.setattr(module.MihomoValidator, "_wait_ready", fake_ready)
    monkeypatch.setattr(module.MihomoValidator, "_probe_one", fake_probe_one)
    results = asyncio.run(validator.validate(nodes))
    assert len(results) == 2
    assert results[0].alive is False
    assert results[1].alive is True
