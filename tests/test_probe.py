import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from squad_vpn.models import ProxyNode, RankedNode, ValidationResult
from squad_vpn.probe import (
    ProbeIdentity,
    build_report,
    load_identity,
    publish_report,
    sync_probes,
    validate_report,
)
from squad_vpn.smart import SmartProfile, select_profile
from squad_vpn.store import NodeStore

NOW = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _nodes():
    return [
        ProxyNode("vless", f"n{i}.example", 443, userinfo=f"u{i}", raw_uri=f"vless://n{i}")
        for i in range(3)
    ]


def _store(path, probe, alive_map, region):
    store = NodeStore(path)
    nodes = _nodes()
    store.upsert_many(nodes)
    store.register_probe(probe, region)
    for node, alive in zip(nodes, alive_map):
        for _ in range(3):
            store.record_validation(
                ValidationResult(
                    node.fingerprint, alive, latency_ms=100 if alive else None,
                    error=None if alive else "timeout", probe_id=probe,
                )
            )
    return store, nodes


def test_region_status():
    item = RankedNode(node=ProxyNode("vless", "h", 443))
    assert item.region_status("RU") == "unknown"
    item.regions = {"RU": {"alive": False}, "US": {"alive": True}}
    assert item.region_status("ru") == "blocked"
    assert item.region_status("US") == "ok"
    item.regions = {"RU": {"alive": False}}
    assert item.region_status("RU") == "down"


def test_report_has_no_personal_data(tmp_path):
    store, _ = _store(tmp_path / "a.sqlite3", "ru-aaaaaa", [True, False, True], "RU")
    try:
        report = build_report(store, ProbeIdentity("ru-aaaaaa", "RU"))
    finally:
        store.close()
    assert set(report) == {"format", "probe_id", "region", "kind", "version", "generated_at", "results"}
    assert len(report["results"]) == 3
    assert set(report["results"][0]) == {"fp", "alive", "latency_ms", "checked_at", "rate", "checks", "error"}
    assert validate_report(json.loads(json.dumps(report)))["region"] == "RU"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(format=99),
        lambda r: r.update(probe_id="../../evil"),
        lambda r: r.update(region="Russia"),
        lambda r: r.update(generated_at="yesterday"),
        lambda r: r.update(
            generated_at=(datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        ),
        lambda r: r.update(results="nope"),
    ],
)
def test_validate_report_rejects_bad_input(mutate):
    report = {"format": 1, "probe_id": "us-1", "region": "US", "generated_at": NOW, "results": []}
    mutate(report)
    with pytest.raises(ValueError):
        validate_report(report)


def test_validate_report_drops_bad_rows():
    report = {
        "format": 1, "probe_id": "us-1", "region": "US", "generated_at": NOW,
        "results": [
            {"fp": "x" * 64, "alive": True, "checked_at": NOW},
            {"fp": "a" * 64, "alive": True, "checked_at": "now"},
            {"fp": "b" * 64, "alive": 1, "checked_at": NOW, "rate": 7, "latency_ms": "fast"},
            "junk",
        ],
    }
    rows = validate_report(report)["results"]
    assert len(rows) == 1 and rows[0]["rate"] == 1.0 and rows[0]["latency_ms"] is None


def test_import_keeps_newer_and_ignores_unknown_nodes(tmp_path):
    store, nodes = _store(tmp_path / "a.sqlite3", "us-local", [True, True, True], "US")
    try:
        fp = nodes[0].fingerprint
        older = "2000-01-01 00:00:00"
        count = store.import_probe_results(
            "ru-remote", "RU",
            [
                {"fp": fp, "alive": False, "checked_at": NOW, "rate": 0.0, "checks": 3},
                {"fp": "f" * 64, "alive": True, "checked_at": NOW},
            ],
        )
        assert count == 1
        store.import_probe_results(
            "ru-remote", "RU", [{"fp": fp, "alive": True, "checked_at": older}]
        )
        node = store.get_ranked(fp)
        assert node.region_status("RU") == "blocked"
        assert node.region_status("US") == "ok"
        probes = {p["probe_id"]: p for p in store.list_probes()}
        assert probes["us-local"]["is_self"] and not probes["ru-remote"]["is_self"]
    finally:
        store.close()


def test_profiles_by_region(tmp_path):
    store, nodes = _store(tmp_path / "a.sqlite3", "us-local", [True, True, True], "US")
    try:
        store.import_probe_results(
            "ru-remote", "RU",
            [
                {"fp": nodes[0].fingerprint, "alive": True, "latency_ms": 300, "checked_at": NOW},
                {"fp": nodes[1].fingerprint, "alive": False, "checked_at": NOW},
                {"fp": nodes[2].fingerprint, "alive": True, "latency_ms": 90, "checked_at": NOW},
            ],
        )
        hosts = lambda p: [r.node.host for r in select_profile(store, p)]  # noqa: E731
        assert hosts(SmartProfile("x", require_regions=("RU",))) == ["n2.example", "n0.example"]
        assert hosts(SmartProfile("x", require_regions=("RU",), max_latency=200)) == ["n2.example"]
        assert "n1.example" not in hosts(SmartProfile("x", avoid_blocked_in=("RU",)))
        assert "n1.example" in hosts(SmartProfile("x"))
    finally:
        store.close()


def test_remote_alive_nodes_are_checked_first(tmp_path):
    store = NodeStore(tmp_path / "a.sqlite3")
    try:
        nodes = _nodes()
        store.upsert_many(nodes)
        store.import_probe_results(
            "us-remote", "US", [{"fp": nodes[2].fingerprint, "alive": True, "checked_at": NOW}]
        )
        first = store.list_validation_candidates(limit=1)
        assert first[0].fingerprint == nodes[2].fingerprint
    finally:
        store.close()


def test_two_probes_exchange_reports_through_git(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    ru_store, nodes = _store(tmp_path / "ru.sqlite3", "ru-home", [False, True, True], "RU")
    us_store, _ = _store(tmp_path / "us.sqlite3", "gh-actions", [True, True, False], "US")
    ru, us = ProbeIdentity("ru-home", "RU"), ProbeIdentity("gh-actions", "US", "github-actions")
    try:
        assert sync_probes(us_store, us, str(remote), cache=tmp_path / "c0")["imported"] == {}
        publish_report(ru_store, ru, str(remote), workdir=tmp_path / "w1")
        publish_report(us_store, us, str(remote), workdir=tmp_path / "w2")
        result = sync_probes(us_store, us, str(remote), cache=tmp_path / "c1")
        assert result["imported"] == {"ru-home": 3}
        statuses = [us_store.get_ranked(n.fingerprint).region_status("RU") for n in nodes]
        assert statuses == ["blocked", "ok", "ok"]
        back = sync_probes(ru_store, ru, str(remote), cache=tmp_path / "c2")
        assert back["imported"] == {"gh-actions": 3}
        assert ru_store.get_ranked(nodes[2].fingerprint).region_status("US") == "blocked"
        assert ru_store.get_ranked(nodes[0].fingerprint).region_status("RU") == "blocked"
    finally:
        ru_store.close()
        us_store.close()


def test_identity_is_stable_and_retries_unknown_region(tmp_path, monkeypatch):
    from squad_vpn import probe

    path = tmp_path / "probe.json"
    monkeypatch.setattr(probe, "detect_region", lambda: "??")
    first = load_identity(path)
    assert first.region == "??" and first.probe_id.startswith("xx-")
    monkeypatch.setattr(probe, "detect_region", lambda: "RU")
    second = load_identity(path)
    assert second.probe_id == first.probe_id and second.region == "RU"
    assert load_identity(path, region="de").region == "DE"
    with pytest.raises(ValueError):
        load_identity(tmp_path / "x.json", probe_id="Bad Id", region="US")


def test_new_probe_is_seeded_from_existing_checks(tmp_path):
    store = NodeStore(tmp_path / "seed.sqlite3")
    try:
        nodes = _nodes()
        store.upsert_many(nodes)
        store.record_validation(ValidationResult(nodes[0].fingerprint, True, latency_ms=80))
        store.record_validation(ValidationResult(nodes[1].fingerprint, False, error="x"))
        store.register_probe("gh-actions", "US")
        rows = {r["fp"]: r for r in store.probe_report_rows("gh-actions")}
        assert rows[nodes[0].fingerprint]["alive"] is True
        assert rows[nodes[1].fingerprint]["alive"] is False
        assert nodes[2].fingerprint not in rows
    finally:
        store.close()
