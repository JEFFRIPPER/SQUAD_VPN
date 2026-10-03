import base64

import pytest
from fastapi.testclient import TestClient

from squad_vpn.api import create_app
from squad_vpn.models import ProxyNode, ValidationResult
from squad_vpn.store import NodeStore


def _seed(database):
    store = NodeStore(database)
    try:
        fast = ProxyNode(
            "trojan", "fast.example", 443, userinfo="pw", name="Fast DE",
            raw_uri="trojan://pw@fast.example:443#Fast",
        )
        slow = ProxyNode(
            "vless", "slow.example", 443,
            userinfo="11111111-1111-1111-1111-111111111111", name="Slow NL",
            raw_uri="vless://11111111-1111-1111-1111-111111111111@slow.example:443",
        )
        dead = ProxyNode("trojan", "dead.example", 443, userinfo="pw", raw_uri="trojan://pw@dead.example:443")
        store.upsert_many([fast, slow, dead])
        for latency in (80, 90, 85):
            store.record_validation(ValidationResult(fast.fingerprint, True, latency_ms=latency, country="DE"))
        for latency in (700, 900, 650):
            store.record_validation(ValidationResult(slow.fingerprint, True, latency_ms=latency, country="NL"))
        store.record_validation(ValidationResult(dead.fingerprint, False, error="timeout"))
        return fast, slow, dead
    finally:
        store.close()


@pytest.fixture()
def seeded(tmp_path):
    database = tmp_path / "api.sqlite3"
    nodes = _seed(database)
    return database, nodes


def test_health_and_dashboard_are_public(seeded):
    database, _ = seeded
    client = TestClient(create_app(database, token="secret"))
    assert client.get("/health").json()["status"] == "ok"
    page = client.get("/")
    assert page.status_code == 200
    assert "SQUAD VPN" in page.text


def test_token_is_required_when_configured(seeded):
    database, _ = seeded
    client = TestClient(create_app(database, token="secret"))
    assert client.get("/api/stats").status_code == 401
    assert client.get("/sub").status_code == 401
    assert client.get("/api/stats?token=wrong").status_code == 401
    assert client.get("/api/stats?token=secret").status_code == 200
    headers = {"Authorization": "Bearer secret"}
    assert client.get("/api/stats", headers=headers).status_code == 200


def test_sub_formats_and_filters(seeded):
    database, (fast, slow, dead) = seeded
    client = TestClient(create_app(database))

    plain = client.get("/sub")
    assert plain.status_code == 200
    assert plain.headers["x-squad-nodes"] == "2"
    assert fast.raw_uri in plain.text and slow.raw_uri in plain.text
    assert dead.raw_uri not in plain.text

    fast_only = client.get("/sub", params={"profile": "fast"})
    assert fast_only.text.strip() == fast.raw_uri

    by_country = client.get("/sub", params={"country": "nl"})
    assert by_country.text.strip() == slow.raw_uri

    encoded = client.get("/sub", params={"format": "base64", "protocol": "trojan"})
    assert base64.b64decode(encoded.text).decode().strip() == fast.raw_uri

    yaml_sub = client.get("/sub", params={"format": "mihomo", "limit": 1})
    assert yaml_sub.headers["content-type"].startswith("text/yaml")
    assert "proxies:" in yaml_sub.text
    assert yaml_sub.headers["x-squad-nodes"] == "1"

    assert client.get("/sub", params={"profile": "nope"}).status_code == 404
    assert client.get("/sub", params={"format": "exe"}).status_code == 422


def test_profile_defaults_can_be_overridden(seeded):
    database, (fast, slow, _) = seeded
    client = TestClient(create_app(database))
    relaxed = client.get("/sub", params={"profile": "fast", "max_latency": 2000})
    assert slow.raw_uri in relaxed.text


def test_nodes_pagination_sorting_and_no_secrets(seeded):
    database, (fast, slow, dead) = seeded
    client = TestClient(create_app(database))

    page = client.get("/api/nodes", params={"limit": 2}).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["items"][0]["fingerprint"] == fast.fingerprint
    assert "raw_uri" not in page["items"][0]
    assert "userinfo" not in page["items"][0]

    rest = client.get("/api/nodes", params={"limit": 2, "offset": 2}).json()
    assert [item["fingerprint"] for item in rest["items"]] == [dead.fingerprint]

    alive = client.get("/api/nodes", params={"alive_only": True, "sort": "latency"}).json()
    assert [item["fingerprint"] for item in alive["items"]] == [fast.fingerprint, slow.fingerprint]

    assert client.get("/api/nodes", params={"sort": "drop table"}).status_code == 422


def test_node_detail_has_history(seeded):
    database, (fast, _, _) = seeded
    client = TestClient(create_app(database))
    detail = client.get(f"/api/nodes/{fast.fingerprint}").json()
    assert detail["country"] == "DE"
    assert [item["latency_ms"] for item in detail["history"]] == [80, 90, 85]
    assert all(item["probe_id"] == "local" for item in detail["history"])
    assert client.get("/api/nodes/unknown").status_code == 404


def test_stats_and_sources(seeded):
    from squad_vpn.sources import SourceReport, SourceSpec

    database, _ = seeded
    store = NodeStore(database)
    try:
        store.record_source_report(
            SourceReport(SourceSpec("demo", "https://example.com", tags=("a",)), True, 10, 5, 12.0)
        )
    finally:
        store.close()
    client = TestClient(create_app(database))
    stats = client.get("/api/stats").json()
    assert stats["total"] == 3 and stats["alive"] == 2 and stats["dead"] == 1
    assert stats["countries"]["DE"] == {"total": 1, "alive": 1}
    assert stats["protocols"]["trojan"]["total"] == 2
    sources = client.get("/api/sources").json()
    assert sources[0]["name"] == "demo"
    assert sources[0]["tags"] == ["a"]


def test_database_uses_wal(tmp_path):
    store = NodeStore(tmp_path / "wal.sqlite3")
    try:
        mode = store.connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        store.close()


def test_serve_refuses_public_host_without_token(capsys):
    from squad_vpn.cli import build_parser, _serve

    args = build_parser().parse_args(["serve", "--host", "0.0.0.0"])
    assert _serve(args) == 2
    assert "token" in capsys.readouterr().out
