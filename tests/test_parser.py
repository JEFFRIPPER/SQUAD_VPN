import base64
import json

from squad_vpn.parser import deduplicate, parse_subscription, parse_uri


UUID = "11111111-1111-1111-1111-111111111111"


def test_vless_parse():
    uri = "vless://" + UUID + "@vpn.example.com:443"
    uri += "?security=reality&type=xhttp&sni=example.com#Germany"
    node = parse_uri(uri)
    assert node is not None
    assert node.protocol == "vless"
    assert node.host == "vpn.example.com"
    assert node.port == 443
    assert node.params["security"] == "reality"
    assert node.name == "Germany"


def test_comment_does_not_change_fingerprint():
    base = "vless://" + UUID + "@vpn.example.com:443?security=tls"
    a = parse_uri(base + "#One")
    b = parse_uri(base + "#Two")
    assert a is not None and b is not None
    assert a.fingerprint == b.fingerprint
    assert len(deduplicate([a, b])) == 1


def test_vmess_parse():
    payload = {
        "v": "2",
        "ps": "VMess test",
        "add": "vmess.example.com",
        "port": "443",
        "id": UUID,
        "net": "ws",
        "tls": "tls",
    }
    raw = json.dumps(payload).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    node = parse_uri("vmess://" + encoded)
    assert node is not None
    assert node.protocol == "vmess"
    assert node.host == "vmess.example.com"
    assert node.port == 443


def test_base64_subscription():
    plain = "vless://" + UUID + "@one.example.com:443?security=tls#One\n"
    plain += "trojan://secret@two.example.com:443?security=tls#Two\n"
    encoded = base64.urlsafe_b64encode(plain.encode("utf-8")).decode("ascii")
    nodes = parse_subscription(encoded, source="memory")
    assert [node.protocol for node in nodes] == ["vless", "trojan"]
    assert all(node.source == "memory" for node in nodes)
