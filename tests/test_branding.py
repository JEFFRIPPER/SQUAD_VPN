import base64
import json

import yaml

from squad_vpn.branding import Branding, ProfileBranding, encode_value, flag, load_branding, rename_uri
from squad_vpn.models import ProxyNode, RankedNode
from squad_vpn.parser import parse_subscription
from squad_vpn.smart import render_subscription


def _decode(value):
    assert value.startswith("base64:")
    return base64.b64decode(value[7:]).decode("utf-8")


def _vmess(name="old"):
    data = {"v": "2", "ps": name, "add": "vm.example", "port": "443", "id": "uuid-1", "net": "ws", "tls": "tls"}
    return "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()


def _records():
    vless = "vless://u@de.example:443?security=reality&pbk=k#%40junk_channel"
    return [
        RankedNode(ProxyNode("vless", "de.example", 443, userinfo="u", params={"security": "reality", "pbk": "k"},
                             name="@junk_channel", raw_uri=vless), country="DE"),
        RankedNode(ProxyNode("vless", "de2.example", 443, userinfo="u", raw_uri="vless://u@de2.example:443"),
                   country="DE"),
        RankedNode(ProxyNode("vmess", "vm.example", 443, userinfo="uuid-1", params={"net": "ws", "tls": "tls"},
                             name="old", raw_uri=_vmess()), country=None),
    ]


def test_encode_value_and_flag():
    assert encode_value("SQUAD VPN") == "SQUAD VPN"
    assert _decode(encode_value("SQUAD · Топ")) == "SQUAD · Топ"
    assert _decode(encode_value("две\nстроки")) == "две строки"
    assert flag("de") == "🇩🇪" and flag(None) == "🌐"


def test_titles_announce_and_overrides():
    branding = Branding(
        announce="Узлов: {count}",
        support_url="https://t.me/squad",
        profiles={"top": ProfileBranding(title="{brand} · Топ-10", announce="Лучшие")},
    )
    top = branding.metadata("top", "10 лучших", 10)
    assert _decode(top["profile-title"]) == "SQUAD VPN · Топ-10"
    assert _decode(top["announce"]) == "Лучшие"
    assert top["support-url"] == "https://t.me/squad"
    other = branding.metadata("fast", "Самые быстрые", 7)
    assert _decode(other["profile-title"]) == "SQUAD VPN · Самые быстрые"
    assert _decode(other["announce"]) == "Узлов: 7"
    assert "profile-web-page-url" not in other  # empty values are not sent
    assert branding.body_header("top", "", 1).startswith("#profile-title: base64:")


def test_node_names_rename_links_without_breaking_them():
    branding = Branding()
    nodes = branding.apply(_records())
    assert [node.name for node in nodes] == ["🇩🇪 Германия 1", "🇩🇪 Германия 2", "🌐 Мир 1"]
    # Re-parsing the renamed links gives the same servers with the new names.
    parsed = parse_subscription("\n".join(node.raw_uri for node in nodes))
    assert [node.name for node in parsed] == [node.name for node in nodes]
    original = parse_subscription("\n".join(item.node.raw_uri for item in _records()))
    assert [node.fingerprint for node in parsed] == [node.fingerprint for node in original]


def test_rename_keeps_vmess_settings():
    node = _records()[2].node
    data = json.loads(base64.b64decode(rename_uri(node, "Новое имя").split("://", 1)[1]))
    assert data["ps"] == "Новое имя" and data["add"] == "vm.example" and data["net"] == "ws"


def test_empty_node_name_keeps_source_names():
    nodes = Branding(node_name="").apply(_records())
    assert nodes[0].raw_uri == _records()[0].node.raw_uri


def test_rendered_subscription_formats():
    rendered = render_subscription(_records(), Branding(), "top", "Топ")
    assert rendered.plain.startswith("#profile-title: base64:")
    assert base64.b64decode(rendered.base64).decode("utf-8") == rendered.plain
    config = yaml.safe_load(rendered.mihomo)
    names = [proxy["name"] for proxy in config["proxies"]]
    assert names == ["🇩🇪 Германия 1", "🇩🇪 Германия 2", "🌐 Мир 1"]
    assert len(parse_subscription(rendered.plain)) == 3  # metadata lines are skipped


def test_load_branding_from_yaml(tmp_path):
    path = tmp_path / "branding.yaml"
    path.write_text(
        "brand: MY VPN\nnode_name: ''\nprofiles:\n  top:\n    title: Лучшее\n",
        encoding="utf-8",
    )
    branding = load_branding(path)
    assert branding.brand == "MY VPN" and branding.node_name == ""
    assert branding.title_for("top") == "Лучшее"
    assert branding.title_for("all", "Все") == "MY VPN · Все"
    assert load_branding(tmp_path / "missing.yaml") == Branding()


def test_repository_branding_file_is_valid():
    branding = load_branding("config/branding.yaml")
    assert branding.title_for("top")
    assert branding.title_for("top") == "SQUAD VPN"
    assert branding.announce_for("top") == "Бесплатная подписка VPN от Сквада."


def test_unknown_country_comes_from_the_source_flag():
    from squad_vpn.branding import country_from_flag

    assert country_from_flag("🇵🇱 Poland | [*CIDR] VK") == "PL"
    assert country_from_flag("plain name") is None
    record = RankedNode(ProxyNode("vless", "h.example", 443, userinfo="u", name="🇵🇱 Poland", raw_uri="vless://u@h.example:443"))
    assert Branding().node_names([record]) == ["🇵🇱 Польша 1"]
