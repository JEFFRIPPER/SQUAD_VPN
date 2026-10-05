import pytest
import yaml
from fastapi.testclient import TestClient

from squad_vpn.exporter import mihomo_config
from squad_vpn.models import ProxyNode, RankedNode, ValidationResult
from squad_vpn.scoring import representative_latency, weighted_success_rate
from squad_vpn.smart import (
    DEFAULT_PROFILES,
    SmartProfile,
    by_name,
    diversify,
    load_profiles,
    select_profile,
)
from squad_vpn.store import NodeStore


def test_weighted_success_favors_recent_checks():
    recovered = weighted_success_rate([True, True, False, False, False])
    broke = weighted_success_rate([False, False, True, True, True])
    assert recovered > 0.5 > broke
    assert weighted_success_rate([]) == 0.0
    assert weighted_success_rate([True] * 5) == 1.0


def test_representative_latency_is_median():
    assert representative_latency([100, 900, 110]) == 110
    assert representative_latency([100, 120]) == 110
    assert representative_latency([]) is None


def test_single_spike_does_not_reshuffle(tmp_path):
    store = NodeStore(tmp_path / "spike.sqlite3")
    try:
        node = ProxyNode("trojan", "a.example", 443, userinfo="pw", raw_uri="t")
        store.upsert_many([node])
        for latency in (100, 110, 105, 1500):
            store.record_validation(ValidationResult(node.fingerprint, True, latency_ms=latency))
        assert store.list_ranked()[0].latency_ms == pytest.approx(107.5)
    finally:
        store.close()


def _ranked(host, exit_ip=None, asn=None, country=None, protocol="vless"):
    return RankedNode(
        node=ProxyNode(protocol, host, 443, userinfo=host, raw_uri=f"{protocol}://{host}"),
        alive=True,
        exit_ip=exit_ip,
        asn=asn,
        country=country,
    )


def test_diversify_skips_duplicates():
    records = [
        _ranked("a.example", "1.1.1.1", "AS1 X"),
        _ranked("A.example", "1.1.1.2", "AS1 X"),  # same host
        _ranked("b.example", "1.1.1.1", "AS2 Y"),  # same exit IP
        _ranked("c.example", "3.3.3.3", "AS1 X"),
        _ranked("d.example", "4.4.4.4", "AS1 X"),  # ASN cap = 2
        _ranked("e.example", None, None),
    ]
    picked = diversify(records, 10, max_asn_share=0.1)
    assert [r.node.host for r in picked] == ["a.example", "c.example", "e.example"]
    assert len(diversify(records, 10, per_host=None, per_exit_ip=None)) == 6
    assert len(diversify(records, 1)) == 1


def test_load_profiles_from_yaml_and_defaults(tmp_path):
    assert load_profiles(tmp_path / "missing.yaml") == DEFAULT_PROFILES
    path = tmp_path / "profiles.yaml"
    path.write_text(
        "profiles:\n"
        "  - name: de\n    countries: DE\n    per_host: null\n"
        "  - name: noru\n    exclude_countries: [ru]\n    protocols: [vless, trojan]\n",
        encoding="utf-8",
    )
    de, noru = load_profiles(path)
    assert de.countries == ("DE",) and de.per_host is None
    assert noru.exclude_countries == ("ru",) and noru.protocols == ("vless", "trojan")


@pytest.mark.parametrize(
    "body",
    [
        "profiles: []\n",
        "profiles:\n  - name: x\n    bogus: 1\n",
        "profiles:\n  - name: ../evil\n",
        "profiles:\n  - name: a\n  - name: a\n",
    ],
)
def test_load_profiles_rejects_bad_files(tmp_path, body):
    path = tmp_path / "bad.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        load_profiles(path)


def test_repo_profiles_file_is_valid():
    profiles = load_profiles("config/profiles.yaml")
    assert [p.name for p in profiles] == ["top", "best", "whitelist"]
    # Old subscription links keep working as aliases of "best".
    assert set(by_name(profiles)) >= {"all", "balanced", "fast", "stable", "europe", "russia"}
    assert by_name(profiles)["fast"].name == "best"


def _seed(store):
    nodes = {
        "de": ProxyNode("vless", "de.example", 443, userinfo="u1", raw_uri="vless://de"),
        "ru": ProxyNode("trojan", "ru.example", 443, userinfo="u2", raw_uri="trojan://ru"),
        "nl": ProxyNode("trojan", "nl.example", 443, userinfo="u3", raw_uri="trojan://nl"),
    }
    store.upsert_many(list(nodes.values()))
    for key, country, latency in (("de", "DE", 80), ("ru", "RU", 40), ("nl", "NL", 120)):
        for _ in range(3):
            store.record_validation(
                ValidationResult(nodes[key].fingerprint, True, latency_ms=latency, country=country)
            )
    return nodes


def test_select_profile_filters(tmp_path):
    store = NodeStore(tmp_path / "sel.sqlite3")
    try:
        _seed(store)
        hosts = lambda p: [r.node.host for r in select_profile(store, p)]  # noqa: E731
        assert hosts(SmartProfile("x", exclude_countries=("ru",))) == ["de.example", "nl.example"]
        assert hosts(SmartProfile("x", countries=("NL", "DE"))) == ["de.example", "nl.example"]
        assert hosts(SmartProfile("x", protocols=("trojan",), exclude_countries=("RU",))) == ["nl.example"]
        assert hosts(SmartProfile("x", limit=1)) == ["ru.example"]
    finally:
        store.close()


def test_mihomo_config_has_failover_groups():
    nodes = [
        ProxyNode("trojan", f"n{i}.example", 443, userinfo="pw", raw_uri="t") for i in range(3)
    ]
    config = mihomo_config(nodes, "SQUAD fast")
    groups = {g["name"]: g for g in config["proxy-groups"]}
    names = [p["name"] for p in config["proxies"]]
    assert len(set(names)) == 3
    assert groups["AUTO"]["type"] == "url-test" and groups["AUTO"]["proxies"] == names
    assert groups["FAILOVER"]["type"] == "fallback"
    assert groups["SQUAD"]["proxies"][:2] == ["AUTO", "FAILOVER"]
    assert config["rules"][-1] == "MATCH,SQUAD"
    empty = mihomo_config([])
    assert empty["proxy-groups"] == [{"name": "SQUAD", "type": "select", "proxies": ["DIRECT"]}]


def test_sub_uses_custom_profiles_file(tmp_path):
    from squad_vpn.api import create_app

    database = tmp_path / "api.sqlite3"
    store = NodeStore(database)
    try:
        _seed(store)
    finally:
        store.close()
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        "profiles:\n  - name: noru\n    description: Без России\n    exclude_countries: [RU]\n"
        "    aliases: [old]\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(database, profiles_path=profiles))
    assert list(client.get("/api/profiles").json()) == ["noru"]
    assert client.get("/api/profiles").json()["noru"]["description"] == "Без России"
    assert client.get("/sub", params={"profile": "old"}).text == client.get("/sub", params={"profile": "noru"}).text
    body = client.get("/sub", params={"profile": "noru"}).text.splitlines()
    assert [line.split("#")[0] for line in body if not line.startswith("#")] == ["vless://de", "trojan://nl"]
    assert client.get("/sub", params={"profile": "balanced"}).status_code == 404
    mihomo = yaml.safe_load(client.get("/sub", params={"profile": "noru", "format": "mihomo"}).text)
    assert {g["name"] for g in mihomo["proxy-groups"]} == {"SQUAD", "AUTO", "FAILOVER"}


def test_scores_recomputed_when_scoring_changes(tmp_path):
    database = tmp_path / "ver.sqlite3"
    store = NodeStore(database)
    try:
        node = ProxyNode("trojan", "a.example", 443, userinfo="pw", raw_uri="t")
        store.upsert_many([node])
        for latency in (100, 110, 900):
            store.record_validation(ValidationResult(node.fingerprint, True, latency_ms=latency))
        store.connection.execute("UPDATE nodes SET latency_ms = 900, quality_score = 1")
        store.connection.execute("UPDATE meta SET value = '1' WHERE key = 'scoring_version'")
        store.connection.commit()
    finally:
        store.close()
    store = NodeStore(database)
    try:
        ranked = store.list_ranked()[0]
        assert ranked.latency_ms == 110
        assert ranked.quality_score > 50
    finally:
        store.close()
