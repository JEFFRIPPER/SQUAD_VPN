from squad_vpn.mihomo import build_runtime_config, node_to_mihomo
from squad_vpn.parser import parse_uri


UUID = "11111111-1111-1111-1111-111111111111"


def test_vless_reality_xhttp_conversion():
    uri = "vless://" + UUID + "@vpn.example.com:443"
    uri += "?security=reality&type=xhttp&sni=front.example.com"
    uri += "&pbk=PUBLICKEY&sid=abcd&path=%2Fapi&host=cdn.example.com"
    node = parse_uri(uri)
    assert node is not None
    proxy = node_to_mihomo(node, "test")
    assert proxy is not None
    assert proxy["type"] == "vless"
    assert proxy["tls"] is True
    assert proxy["network"] == "xhttp"
    assert proxy["reality-opts"]["public-key"] == "PUBLICKEY"
    assert proxy["xhttp-opts"]["path"] == "/api"


def test_runtime_config_has_controller_and_group():
    node = parse_uri(f"trojan://secret@example.com:443?sni=example.com")
    assert node is not None
    config, converted = build_runtime_config(
        [node], controller_port=19090, mixed_port=17890
    )
    assert config["external-controller"] == "127.0.0.1:19090"
    assert config["mixed-port"] == 17890
    assert config["proxy-groups"][0]["name"] == "SQUAD-VALIDATOR"
    assert len(converted) == 1
    assert converted[0].fingerprint == node.fingerprint


def test_mihomo_asset_names_per_platform():
    from squad_vpn.setup_mihomo import asset_name

    assert asset_name("v1.19.0", "Windows", "AMD64") == "mihomo-windows-amd64-compatible-v1.19.0.zip"
    assert asset_name("v1.19.0", "Linux", "x86_64") == "mihomo-linux-amd64-compatible-v1.19.0.gz"
    assert asset_name("v1.19.0", "Linux", "aarch64") == "mihomo-linux-arm64-v1.19.0.gz"
    assert asset_name("v1.19.0", "Darwin", "arm64") == "mihomo-darwin-arm64-v1.19.0.gz"


def test_mihomo_extracts_gzip_binary():
    import gzip

    from squad_vpn.setup_mihomo import extract_binary

    assert extract_binary("mihomo-linux-amd64-compatible-v1.gz", gzip.compress(b"ELF")) == b"ELF"
