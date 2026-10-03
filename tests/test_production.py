import gzip
import io
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from squad_vpn.backup import backup_due, create_backup, list_backups, restore_backup
from squad_vpn.config import load_config
from squad_vpn.keys import KeyStore, allows
from squad_vpn.models import ProxyNode, ValidationResult
from squad_vpn.ratelimit import RateLimiter, TtlCache
from squad_vpn.store import NodeStore


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_config_file_and_env_overrides(tmp_path):
    path = tmp_path / "squad.yaml"
    path.write_text("logging: {level: debug}\nbackup: {keep: 3}\ncache: {sub_seconds: nope}\n", encoding="utf-8")
    config = load_config(path, env={"SQUAD_BACKUP_KEEP": "14", "SQUAD_RATE_LIMIT_SUB_PER_MINUTE": "5"})
    assert config.logging.level == "DEBUG"
    assert config.backup.keep == 14
    assert config.rate_limit.sub_per_minute == 5
    assert config.cache.sub_seconds == 60  # bad value keeps the default
    assert load_config(tmp_path / "missing.yaml", env={}).backup.keep == 7


def test_repo_config_parses():
    assert load_config("config/squad.yaml", env={}).rate_limit.api_per_minute == 120


def test_keys_are_hashed_scoped_and_revocable(tmp_path):
    store = KeyStore(tmp_path / "keys.json")
    key, token = store.create("телефон", "sub")
    assert token.startswith("sq_") and token not in (tmp_path / "keys.json").read_text(encoding="utf-8")
    assert store.match(token).name == "телефон"
    assert store.match("sq_wrong") is None
    assert allows("sub", "sub") and not allows("sub", "read") and allows("admin", "read")
    with pytest.raises(ValueError):
        store.create("телефон", "sub")
    with pytest.raises(ValueError):
        store.create("x", "root")
    assert store.revoke("телефон") and store.match(token) is None


def test_rate_limiter_window_and_ban():
    clock = Clock()
    limiter = RateLimiter(clock)
    assert all(limiter.hit("1.1.1.1", "sub", 3) == 0 for _ in range(3))
    assert limiter.hit("1.1.1.1", "sub", 3) > 0
    assert limiter.hit("2.2.2.2", "sub", 3) == 0
    clock.now += 61
    assert limiter.hit("1.1.1.1", "sub", 3) == 0
    for _ in range(3):
        limiter.auth_failure("6.6.6.6", 2, 600)
    assert limiter.blocked_for("6.6.6.6") > 500
    clock.now += 601
    assert limiter.blocked_for("6.6.6.6") == 0


def test_ttl_cache_expiry_and_invalidation():
    clock = Clock()
    cache = TtlCache(clock)
    cache.set("a", 1, 10)
    assert cache.get("a") == 1
    clock.now += 11
    assert cache.get("a") is None
    cache.set("b", 2, 10)
    cache.invalidate()
    assert cache.get("b") is None


def _db(path):
    store = NodeStore(path)
    node = ProxyNode("trojan", "a.example", 443, userinfo="pw", raw_uri="trojan://a")
    store.upsert_many([node])
    for _ in range(3):
        store.record_validation(ValidationResult(node.fingerprint, True, latency_ms=90, country="DE"))
    store.close()
    return node


def test_backup_rotation_and_restore(tmp_path):
    database = tmp_path / "db.sqlite3"
    _db(database)
    folder = tmp_path / "backups"
    assert backup_due(folder)
    first = create_backup(database, folder, keep=2)
    assert gzip.open(first).read(16).startswith(b"SQLite format 3")
    assert not backup_due(folder, every_hours=24)
    names = [create_backup(database, folder, keep=2).name for _ in range(2)]
    assert len(list_backups(folder)) == 2
    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM nodes")
    connection.commit()
    connection.close()
    restore_backup(list_backups(folder)[0]["name"], database, folder)
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
    connection.close()
    assert any(p.name.startswith("db.sqlite3.before-restore-") for p in tmp_path.iterdir())
    with pytest.raises(FileNotFoundError):
        restore_backup("../db.sqlite3", database, folder)
    assert names


def _app(tmp_path, token=None, **config_env):
    from squad_vpn.api import create_app

    database = tmp_path / "db.sqlite3"
    _db(database)
    config = load_config(tmp_path / "none.yaml", env=config_env)
    return create_app(database, token=token, profiles_path=None, client_root=tmp_path, config=config)


def test_scoped_keys_from_the_network(tmp_path):
    app = _app(tmp_path)
    keys = KeyStore(tmp_path / "data" / "api_keys.json")
    _, sub_token = keys.create("phone", "sub")
    _, read_token = keys.create("laptop", "read")
    remote = TestClient(app, client=("192.168.1.20", 5000))
    assert remote.get("/sub").status_code == 401
    assert remote.get("/sub", params={"token": sub_token}).status_code == 200
    forbidden = remote.get("/api/stats", params={"token": sub_token})
    assert forbidden.status_code == 403 and "phone" in forbidden.json()["detail"]
    assert remote.get("/api/stats", headers={"Authorization": f"Bearer {read_token}"}).status_code == 200
    local = TestClient(app, client=("127.0.0.1", 5000))
    assert local.get("/api/stats").status_code == 200  # this computer needs no key
    assert local.get("/api/keys").json()["keys"][0]["name"] == "phone"
    assert "hash" not in local.get("/api/keys").json()["keys"][0]


def test_wrong_keys_get_the_address_banned(tmp_path):
    app = _app(tmp_path, SQUAD_RATE_LIMIT_AUTH_FAILURES_PER_MINUTE="3")
    KeyStore(tmp_path / "data" / "api_keys.json").create("phone", "sub")
    remote = TestClient(app, client=("10.0.0.9", 5000))
    codes = [remote.get("/sub", params={"token": f"guess{i}"}).status_code for i in range(6)]
    assert codes[:3] == [401, 401, 401] and 429 in codes


def test_rate_limit_and_sub_cache(tmp_path):
    app = _app(tmp_path, SQUAD_RATE_LIMIT_SUB_PER_MINUTE="3")
    remote = TestClient(app, client=("10.0.0.7", 5000))
    responses = [remote.get("/sub") for _ in range(4)]
    assert [r.status_code for r in responses] == [200, 200, 200, 429]
    assert "Retry-After" in responses[-1].headers
    local = TestClient(app, client=("127.0.0.1", 5000))
    first = local.get("/sub").text
    store = NodeStore(tmp_path / "db.sqlite3")
    store.connection.execute("DELETE FROM nodes")
    store.connection.commit()
    store.close()
    assert local.get("/sub").text == first  # served from cache until the next cycle


def test_friendly_errors(tmp_path, monkeypatch):
    app = _app(tmp_path)
    client = TestClient(app, client=("127.0.0.1", 5000), raise_server_exceptions=False)
    assert client.get("/api/nope").json()["detail"] == "Не найдено"
    from squad_vpn.store import NodeStore as Store

    monkeypatch.setattr(Store, "list_probes", lambda self: 1 / 0)
    broken = client.get("/api/probes")
    assert broken.status_code == 500 and "ZeroDivisionError" in broken.json()["detail"]


def test_backup_and_doctor_endpoints(tmp_path):
    app = _app(tmp_path)
    local = TestClient(app, client=("127.0.0.1", 5000))
    name = local.post("/api/backups").json()["name"]
    assert local.get("/api/backups").json()["backups"][0]["name"] == name
    assert local.post("/api/backups/nope/restore").status_code == 404
    report = local.get("/api/doctor").json()
    ids = {check["id"] for check in report["checks"]}
    assert {"python", "database", "disk", "backup"} <= ids
    assert report["status"] in {"ok", "warn", "error"}


def test_launcher_unpacks_source_safely(tmp_path, monkeypatch):
    from tests.test_app import _launcher

    launcher = _launcher()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SQUAD_VPN-main/", "")
        archive.writestr("SQUAD_VPN-main/pyproject.toml", "x")
        archive.writestr("SQUAD_VPN-main/src/a.py", "y")
        archive.writestr("SQUAD_VPN-main/../../evil.txt", "z")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda url, timeout: Response(buffer.getvalue()))
    target = tmp_path / "install"
    launcher.download_source(target)
    assert (target / "pyproject.toml").read_text() == "x"
    assert (target / "src" / "a.py").exists()
    assert not (tmp_path / "evil.txt").exists()


def test_dns_rebinding_and_csrf_are_blocked(tmp_path):
    app = _app(tmp_path)
    local = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 5000))
    assert local.get("/api/stats").status_code == 200
    rebinding = TestClient(app, base_url="http://evil.example:8080", client=("127.0.0.1", 5000))
    assert rebinding.get("/api/stats").status_code == 403
    assert local.post("/api/backups", headers={"Origin": "https://evil.example"}).status_code == 403
    assert local.post("/api/backups", headers={"Origin": "http://127.0.0.1:8081"}).status_code == 403
    assert local.post("/api/backups", headers={"Origin": "http://127.0.0.1:8080"}).status_code == 200
    assert local.post("/api/backups").status_code == 200  # no Origin: not a browser
    lan = TestClient(app, base_url="http://192.168.1.5:8080", client=("192.168.1.20", 5000))
    assert lan.get("/sub").status_code == 200  # IP addresses are fine


def test_cycle_run_needs_admin_from_network(tmp_path):
    app = _app(tmp_path)
    keys = KeyStore(tmp_path / "data" / "api_keys.json")
    _, read_token = keys.create("viewer", "read")
    remote = TestClient(app, client=("10.0.0.3", 5000))
    assert remote.post("/api/cycle/run", params={"token": read_token}).status_code == 403


def test_every_subprocess_call_hides_its_window():
    """Under pythonw a console program without CREATE_NO_WINDOW flashes a window."""
    import ast
    from pathlib import Path

    offenders = []
    for path in Path("src/squad_vpn").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"run", "Popen"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and not any(k.arg == "creationflags" for k in node.keywords)
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
