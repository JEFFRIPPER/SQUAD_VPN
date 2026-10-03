from __future__ import annotations

import base64
import json
from urllib.parse import parse_qsl, unquote, urlsplit

from .models import ProxyNode

SUPPORTED = {"vless", "vmess", "trojan", "ss", "hysteria2", "hy2"}


def _valid_port(port: int) -> bool:
    return 0 < port <= 65535


def _b64decode(value: str) -> bytes:
    value = value.strip()
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def decode_subscription(text: str) -> str:
    stripped = text.strip().lstrip("\ufeff")
    if not stripped:
        return ""
    if "://" in stripped:
        return stripped
    try:
        decoded = _b64decode(stripped).decode("utf-8-sig")
    except (ValueError, UnicodeDecodeError):
        return stripped
    return decoded if "://" in decoded else stripped


def _params(query: str) -> dict[str, str]:
    return {str(k): str(v) for k, v in parse_qsl(query, keep_blank_values=True)}


def _parse_standard(uri: str, source: str) -> ProxyNode | None:
    parsed = urlsplit(uri)
    protocol = parsed.scheme.lower()
    if protocol == "hy2":
        protocol = "hysteria2"
    if protocol not in SUPPORTED or not parsed.hostname or not parsed.port:
        return None
    if not _valid_port(int(parsed.port)):
        return None
    return ProxyNode(
        protocol=protocol,
        host=parsed.hostname,
        port=int(parsed.port),
        userinfo=unquote(parsed.username or ""),
        params=_params(parsed.query),
        name=unquote(parsed.fragment or ""),
        source=source,
        raw_uri=uri,
    )


def _parse_vmess(uri: str, source: str) -> ProxyNode | None:
    payload = uri.split("://", 1)[1].split("#", 1)[0]
    try:
        decoded = _b64decode(payload).decode("utf-8")
        data = json.loads(decoded)
        if not isinstance(data, dict):
            return None
        host = str(data.get("add", "")).strip()
        port = int(data.get("port", 0))
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not host or not _valid_port(port):
        return None
    params = {
        str(k): str(v)
        for k, v in data.items()
        if k not in {"add", "port", "ps", "id"} and v not in (None, "")
    }
    return ProxyNode(
        protocol="vmess",
        host=host,
        port=port,
        userinfo=str(data.get("id", "")),
        params=params,
        name=str(data.get("ps", "")),
        source=source,
        raw_uri=uri,
    )


def _parse_ss(uri: str, source: str) -> ProxyNode | None:
    body = uri.split("://", 1)[1]
    body, _, fragment = body.partition("#")
    body, _, query = body.partition("?")
    if "@" not in body:
        try:
            body = _b64decode(body).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    auth, sep, endpoint = body.rpartition("@")
    if not sep:
        return None
    if ":" not in auth:
        try:
            auth = _b64decode(auth).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    method, sep, password = auth.partition(":")
    host, sep, port = endpoint.rpartition(":")
    if not sep or not method or not password:
        return None
    try:
        port_i = int(port)
    except ValueError:
        return None
    host = host.strip("[]")
    if not host or not _valid_port(port_i):
        return None
    return ProxyNode(
        protocol="ss",
        host=host,
        port=port_i,
        userinfo=f"{method}:{password}",
        params=_params(query),
        name=unquote(fragment),
        source=source,
        raw_uri=uri,
    )


def parse_uri(uri: str, source: str = "") -> ProxyNode | None:
    uri = uri.strip()
    if not uri or "://" not in uri:
        return None
    scheme = uri.split("://", 1)[0].lower()
    try:
        if scheme == "vmess":
            return _parse_vmess(uri, source)
        if scheme == "ss":
            return _parse_ss(uri, source)
        return _parse_standard(uri, source)
    except (ValueError, UnicodeError):
        return None


def parse_subscription(text: str, source: str = "") -> list[ProxyNode]:
    decoded = decode_subscription(text)
    result: list[ProxyNode] = []
    for line in decoded.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        node = parse_uri(line, source=source)
        if node is not None:
            result.append(node)
    return result


def deduplicate(nodes: list[ProxyNode]) -> list[ProxyNode]:
    unique: dict[str, ProxyNode] = {}
    for node in nodes:
        unique.setdefault(node.fingerprint, node)
    return list(unique.values())
