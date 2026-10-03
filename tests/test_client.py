import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from squad_vpn import client as client_module
from squad_vpn import sysproxy
from squad_vpn.client import VpnClient, build_client_config, cleanup_orphan
from squad_vpn.models import ProxyNode, ValidationResult
from squad_vpn.store import NodeStore


class FakeBackend(sysproxy.ProxyBackend):
    supported = True

    def __init__(self, state=None):
        self.state = state or sysproxy.ProxyState(True, "corp:3128", "*.corp")

    def read(self):
        return sysproxy.ProxyState(**self.state.as_dict())

    def write(self, state):
        self.state = state


def test_proxy_restore_respects_user_changes():
    backend = FakeBackend()
    previous = sysproxy.enable(backend, 7890)
    assert backend.state.server == "127.0.0.1:7890"
    assert sysproxy.restore(backend, previous, 7890) is True
    assert backend.state == sysproxy.ProxyState(True, "corp:3128", "*.corp")
    sysproxy.enable(backend, 7890)
    backend.state = sysproxy.ProxyState(True, "other:8080", "")
    assert sysproxy.restore(backend, previous, 7890) is False
    assert backend.state.server == "other:8080"


def _nodes():
    return [
        ProxyNode("trojan", f"n{i}.example", 443, userinfo=f"pw{i}", raw_uri=f"trojan://n{i}")
        for i in range(3)
    ]


def test_client_config_is_tuned_for_everyday_use():
    config, names = build_client_config(_nodes(), secret="s", mixed_port=1, controller_port=2)
    assert config["secret"] == "s" and config["external-controller"] == "127.0.0.1:2"
    assert config["bind-address"] == "127.0.0.1" and config["allow-lan"] is False
    auto = next(g for g in config["proxy-groups"] if g["name"] == "AUTO")
    assert auto["lazy"] is False and auto["interval"] == 120
    assert len(names) == 3 and set(names.values()) == {n.fingerprint for n in _nodes()}


class FakeCore:
    """Minimal Mihomo controller: url-test picks the first node that 'works'."""

    def __init__(self, names):
        self.names = names
        self.dead = set()
        self.selected = "AUTO"
        self.totals = [0, 0]
        self.reloads = 0

    def best(self):
        alive = [n for n in self.names if n not in self.dead]
        return alive[0] if alive else self.names[0]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/version":
            return httpx.Response(200, json={"version": "fake"})
        if path == "/connections":
            self.totals = [self.totals[0] + 1000, self.totals[1] + 50000]
            return httpx.Response(200, json={"uploadTotal": self.totals[0], "downloadTotal": self.totals[1]})
        if path == "/proxies/SQUAD" and request.method == "GET":
            return httpx.Response(200, json={"now": self.selected})
        if path == "/proxies/SQUAD" and request.method == "PUT":
            self.selected = json.loads(request.content)["name"]
            return httpx.Response(204)
        if path in ("/proxies/AUTO", "/proxies/FAILOVER"):
            return httpx.Response(200, json={"now": self.best()})
        if path.startswith("/proxies/") and path.endswith("/delay"):
            name = path[len("/proxies/"):-len("/delay")]
            if name in self.dead:
                return httpx.Response(408, json={"message": "timeout"})
            return httpx.Response(200, json={"delay": 120})
        if path == "/group/AUTO/delay":
            return httpx.Response(200, json={n: 120 for n in self.names if n not in self.dead})
        if path == "/configs" and request.method == "PUT":
            self.reloads += 1
            return httpx.Response(204)
        return httpx.Response(404)


class FakeProcess:
    pid = 999999

    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.alive = False


def _make_client(tmp_path, monkeypatch, backend=None):
    database = tmp_path / "db.sqlite3"
    store = NodeStore(database)
    nodes = _nodes()
    store.upsert_many(nodes)
    for node in nodes:
        for latency in (100, 110, 120):
            store.record_validation(ValidationResult(node.fingerprint, True, latency_ms=latency, country="DE"))
    store.close()
    binary = tmp_path / "mihomo"
    binary.write_text("", encoding="utf-8")
    core = {}

    def spawn(command, log_path):
        process = FakeProcess()
        core["process"] = process
        return process

    vpn = VpnClient(
        database, root=tmp_path, profiles_path=None, binary=binary,
        backend=backend or FakeBackend(), spawn=spawn, log=lambda _: None,
    )
    fake = {"core": None}

    def handler(request):
        if fake["core"] is None:
            fake["core"] = FakeCore(list(vpn._names))
        return fake["core"].handler(request)

    vpn._transport = httpx.MockTransport(handler)
    monkeypatch.setattr(client_module, "_core_alive", lambda *a, **k: False)
    return vpn, fake, core


def test_connect_monitor_failover_and_disconnect(tmp_path, monkeypatch):
    backend = FakeBackend()
    vpn, fake, core = _make_client(tmp_path, monkeypatch, backend)

    async def scenario():
        result = await vpn.connect("all")
        assert result["state"] == "connected", result
        assert backend.state.server == "127.0.0.1:7890"
        vpn._monitor.cancel()
        await vpn._health()
        first = vpn.status["node"]
        assert vpn.status["delay_ms"] == 120 and vpn.snapshot()["node_info"]["country"] == "DE"
        await vpn._traffic()
        await vpn._traffic()
        assert vpn.status["speed_down"] > 0 and vpn.snapshot()["session"]["down"] > 0
        fake["core"].dead.add(first)
        await vpn._health()
        await vpn._health()  # second failure triggers the switch
        assert vpn.status["node"] != first and vpn._switches == 1
        pinned = await vpn.choose(list(vpn._names)[2])
        assert pinned["pinned"] == list(vpn._names)[2]
        result = await vpn.disconnect("user")
        assert result["state"] == "disconnected" and result["proxy_restored"]
        assert backend.state.server == "corp:3128"
        assert core["process"].alive is False
        return vpn

    asyncio.run(scenario())
    store = NodeStore(tmp_path / "db.sqlite3")
    try:
        kinds = [e["kind"] for e in store.client_events()][::-1]
        assert kinds[:2] == ["connect", "switch"] and kinds[-1] == "disconnect"
        assert store.client_totals()["today"]["sessions"] == 1
        assert store.client_totals()["today"]["switches"] == 1
    finally:
        store.close()
    assert vpn.state.load()["connected"] is False


def test_connect_fails_cleanly_without_binary(tmp_path, monkeypatch):
    backend = FakeBackend()
    vpn, _, _ = _make_client(tmp_path, monkeypatch, backend)
    vpn.binary = tmp_path / "missing"
    result = asyncio.run(vpn.connect("all"))
    assert result["state"] == "error" and "Mihomo" in result["error"]
    assert backend.state.server == "corp:3128"


def test_cleanup_orphan_restores_proxy_and_resume_flag(tmp_path):
    backend = FakeBackend()
    previous = sysproxy.enable(backend, 7890)
    state = client_module.ClientState(tmp_path / "data" / "client" / "state.json")
    state.save({"connected": True, "proxy_set": True, "previous_proxy": previous.as_dict(),
                "pid": 123, "secret": "x", "profile": "all"})
    result = cleanup_orphan(tmp_path, backend=backend, controller_port=1)
    assert result == {"proxy_restored": True, "core_stopped": False}
    assert backend.state.server == "corp:3128"
    assert state.load()["connected"] is True  # crash: reconnect on next start
    cleanup_orphan(tmp_path, backend=backend, clear_resume=True, controller_port=1)
    assert state.load()["connected"] is False


def test_client_api(tmp_path, monkeypatch):
    from squad_vpn.api import create_app

    vpn, _, _ = _make_client(tmp_path, monkeypatch)
    app = create_app(tmp_path / "db.sqlite3", profiles_path=None, client=vpn, client_root=tmp_path)
    with TestClient(app, client=("127.0.0.1", 5000)) as http:
        status = http.get("/api/client").json()
        assert status["state"] == "disconnected" and status["settings"]["profile"] == "balanced"
        assert http.post("/api/client/connect", json={"profile": "nope"}).status_code == 422
        assert http.post("/api/client/failover").status_code == 409
        connected = http.post("/api/client/connect", json={"profile": "all"}).json()
        assert connected["state"] == "connected"
        assert len(http.get("/api/client/nodes").json()) == 3
        assert http.get("/api/client/events").json()[0]["kind"] == "connect"
        assert http.post("/api/client/disconnect").json()["state"] == "disconnected"
    remote = TestClient(app, client=("10.0.0.5", 5000))
    assert remote.post("/api/client/connect", json={}).status_code == 403
