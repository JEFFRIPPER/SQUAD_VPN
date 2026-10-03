from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from .models import ProxyNode


@dataclass(slots=True, frozen=True)
class MihomoProxy:
    fingerprint: str
    name: str
    config: dict[str, Any]


def _first(params: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = params.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _transport(proxy: dict[str, Any], params: dict[str, str], network: str) -> None:
    network = (network or "tcp").lower()
    if network in {"none", "raw"}:
        network = "tcp"
    proxy["network"] = network

    path = _first(params, "path") or "/"
    host = _first(params, "host")
    if network == "ws":
        opts: dict[str, Any] = {"path": path}
        if host:
            opts["headers"] = {"Host": host}
        proxy["ws-opts"] = opts
    elif network == "grpc":
        service = _first(params, "serviceName", "service_name", "grpc-service-name")
        proxy["grpc-opts"] = {"grpc-service-name": service}
    elif network == "xhttp":
        opts = {"path": path}
        if host:
            opts["host"] = host
        mode = _first(params, "mode")
        if mode:
            opts["mode"] = mode
        proxy["xhttp-opts"] = opts
    elif network == "h2":
        opts = {"path": path}
        if host:
            opts["host"] = _split_csv(host)
        proxy["h2-opts"] = opts
    elif network == "http":
        opts = {"path": [path]}
        if host:
            opts["headers"] = {"Host": [host]}
        proxy["http-opts"] = opts


def _tls_common(proxy: dict[str, Any], params: dict[str, str]) -> None:
    sni = _first(params, "sni", "servername", "serverName")
    if sni:
        proxy["servername"] = sni
    fp = _first(params, "fp", "client-fingerprint")
    if fp:
        proxy["client-fingerprint"] = fp
    alpn = _first(params, "alpn")
    if alpn:
        proxy["alpn"] = _split_csv(alpn)
    insecure = _first(params, "allowInsecure", "insecure", "skip-cert-verify")
    if insecure:
        proxy["skip-cert-verify"] = _truthy(insecure)
    pbk = _first(params, "pbk", "public-key")
    sid = _first(params, "sid", "short-id")
    if pbk:
        proxy["reality-opts"] = {"public-key": pbk, "short-id": sid}


def _vless(node: ProxyNode, name: str) -> dict[str, Any]:
    p = node.params
    proxy: dict[str, Any] = {
        "name": name,
        "type": "vless",
        "server": node.host,
        "port": node.port,
        "uuid": node.userinfo,
        "udp": True,
        "encryption": _first(p, "encryption"),
    }
    flow = _first(p, "flow")
    if flow:
        proxy["flow"] = flow
    packet = _first(p, "packetEncoding", "packet-encoding")
    if packet:
        proxy["packet-encoding"] = packet
    security = _first(p, "security").lower()
    if security in {"tls", "reality"}:
        proxy["tls"] = True
    _tls_common(proxy, p)
    _transport(proxy, p, _first(p, "type", "network") or "tcp")
    return proxy


def _trojan(node: ProxyNode, name: str) -> dict[str, Any]:
    p = node.params
    proxy: dict[str, Any] = {
        "name": name,
        "type": "trojan",
        "server": node.host,
        "port": node.port,
        "password": node.userinfo,
        "udp": True,
    }
    sni = _first(p, "sni", "servername", "serverName")
    if sni:
        proxy["sni"] = sni
    fp = _first(p, "fp", "client-fingerprint")
    if fp:
        proxy["client-fingerprint"] = fp
    insecure = _first(p, "allowInsecure", "insecure", "skip-cert-verify")
    if insecure:
        proxy["skip-cert-verify"] = _truthy(insecure)
    pbk = _first(p, "pbk", "public-key")
    if pbk:
        proxy["reality-opts"] = {
            "public-key": pbk,
            "short-id": _first(p, "sid", "short-id"),
        }
    _transport(proxy, p, _first(p, "type", "network") or "tcp")
    return proxy


def _vmess(node: ProxyNode, name: str) -> dict[str, Any]:
    p = node.params
    try:
        alter_id = int(_first(p, "aid", "alterId") or 0)
    except ValueError:
        alter_id = 0
    proxy: dict[str, Any] = {
        "name": name,
        "type": "vmess",
        "server": node.host,
        "port": node.port,
        "uuid": node.userinfo,
        "alterId": alter_id,
        "cipher": _first(p, "scy", "cipher") or "auto",
        "udp": True,
    }
    tls = _first(p, "tls", "security").lower()
    if tls in {"tls", "reality", "1", "true"}:
        proxy["tls"] = True
    _tls_common(proxy, p)
    _transport(proxy, p, _first(p, "net", "network") or "tcp")
    return proxy


def _ss(node: ProxyNode, name: str) -> dict[str, Any] | None:
    if ":" not in node.userinfo:
        return None
    method, password = node.userinfo.split(":", 1)
    if not method or not password:
        return None
    proxy: dict[str, Any] = {
        "name": name,
        "type": "ss",
        "server": node.host,
        "port": node.port,
        "cipher": method,
        "password": password,
        "udp": True,
    }
    plugin = _first(node.params, "plugin")
    if plugin:
        parts = [part for part in plugin.split(";") if part]
        plugin_name = parts[0]
        if plugin_name == "obfs-local":
            plugin_name = "obfs"
        proxy["plugin"] = plugin_name
        opts: dict[str, str] = {}
        for item in parts[1:]:
            key, sep, value = item.partition("=")
            if sep:
                opts[key.replace("obfs-", "")] = value
        if opts:
            proxy["plugin-opts"] = opts
    return proxy


def _hysteria2(node: ProxyNode, name: str) -> dict[str, Any]:
    p = node.params
    proxy: dict[str, Any] = {
        "name": name,
        "type": "hysteria2",
        "server": node.host,
        "port": node.port,
        "password": node.userinfo,
    }
    sni = _first(p, "sni", "servername")
    if sni:
        proxy["sni"] = sni
    insecure = _first(p, "insecure", "allowInsecure", "skip-cert-verify")
    if insecure:
        proxy["skip-cert-verify"] = _truthy(insecure)
    obfs = _first(p, "obfs")
    if obfs:
        proxy["obfs"] = obfs
    obfs_password = _first(p, "obfs-password", "obfsPassword")
    if obfs_password:
        proxy["obfs-password"] = obfs_password
    alpn = _first(p, "alpn")
    if alpn:
        proxy["alpn"] = _split_csv(alpn)
    return proxy


def node_to_mihomo(node: ProxyNode, name: str) -> dict[str, Any] | None:
    if node.protocol == "vless":
        return _vless(node, name)
    if node.protocol == "trojan":
        return _trojan(node, name)
    if node.protocol == "vmess":
        return _vmess(node, name)
    if node.protocol == "ss":
        return _ss(node, name)
    if node.protocol == "hysteria2":
        return _hysteria2(node, name)
    return None


def build_runtime_config(
    nodes: list[ProxyNode],
    *,
    controller_port: int,
    mixed_port: int,
) -> tuple[dict[str, Any], list[MihomoProxy]]:
    converted: list[MihomoProxy] = []
    for index, node in enumerate(nodes, start=1):
        name = f"SVPN-{index:05d}-{node.fingerprint[:8]}"
        proxy = node_to_mihomo(node, name)
        if proxy is None:
            continue
        converted.append(MihomoProxy(node.fingerprint, name, proxy))

    names = [item.name for item in converted]
    config: dict[str, Any] = {
        "mixed-port": mixed_port,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "unified-delay": True,
        "tcp-concurrent": True,
        "external-controller": f"127.0.0.1:{controller_port}",
        "proxies": [item.config for item in converted],
        "proxy-groups": [
            {"name": "SQUAD-VALIDATOR", "type": "select", "proxies": names}
        ],
        "rules": ["MATCH,SQUAD-VALIDATOR"],
    }
    return config, converted


def dump_yaml(config: dict[str, Any]) -> str:
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
