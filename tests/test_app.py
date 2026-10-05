import importlib.util
import socket
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from squad_vpn import appdist
from squad_vpn.agent import COMMANDS, _acquire_control_socket, send_command
from squad_vpn.settings import Settings, load_settings, save_settings

REAL_CLIENT = httpx.Client


def test_settings_roundtrip_and_validation(tmp_path):
    path = tmp_path / "settings.json"
    assert load_settings(path) == Settings()
    save_settings(Settings(interval_minutes=30, auto_update=False), path)
    assert load_settings(path) == Settings(interval_minutes=30, auto_update=False)
    with pytest.raises(ValueError):
        save_settings(Settings(interval_minutes=7), path)
    path.write_text("{broken", encoding="utf-8")
    assert load_settings(path) == Settings()


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_agent_commands_are_delivered(tmp_path):
    port = _free_port()
    control = _acquire_control_socket(port, wait_seconds=0)
    try:
        for command in ("update", "restart", "stop"):
            assert send_command(command, port)
            control.setblocking(True)
            conn, _ = control.accept()
            with conn:
                assert conn.recv(16) == command.encode()
        with pytest.raises(ValueError):
            send_command("rm -rf", port)
    finally:
        control.close()
    assert {b"stop", b"update", b"restart", b"abort"} == COMMANDS


def test_release_base():
    assert appdist.release_base("https://github.com/Owner/Repo.git") == (
        "https://github.com/Owner/Repo/releases/download/app-latest/"
    )
    assert appdist.release_base("https://gitlab.com/x/y.git") is None


def _mock_release(monkeypatch, version, exe=b"MZ" + b"\0" * 1_100_000, status=200, manifest=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(appdist.ASSET_MANIFEST):
            if manifest is None:
                return httpx.Response(404)
            return httpx.Response(200, json=manifest)
        if request.url.path.endswith(appdist.ASSET_VERSION):
            return httpx.Response(status, text=version)
        return httpx.Response(200, content=exe)

    monkeypatch.setattr(
        appdist.httpx, "Client",
        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw),
    )


def test_ensure_app_downloads_and_updates(tmp_path, monkeypatch):
    repo = "https://github.com/Owner/Repo.git"
    _mock_release(monkeypatch, "0.7.5-aaaaaaa")
    assert appdist.ensure_app(tmp_path, repo_url=repo, force=True) == "updated: 0.7.5-aaaaaaa"
    assert (tmp_path / appdist.APP_FILE).read_bytes()[:2] == b"MZ"
    assert appdist.ensure_app(tmp_path, repo_url=repo, force=True).startswith("up to date")
    _mock_release(monkeypatch, "0.7.6-bbbbbbb")
    assert appdist.ensure_app(tmp_path, repo_url=repo, force=True) == "updated: 0.7.6-bbbbbbb"


def test_ensure_app_rejects_non_exe_and_missing_release(tmp_path, monkeypatch):
    repo = "https://github.com/Owner/Repo.git"
    _mock_release(monkeypatch, "1", exe=b"<html>not found</html>")
    assert appdist.ensure_app(tmp_path, repo_url=repo, force=True).startswith("error")
    assert not (tmp_path / appdist.APP_FILE).exists()
    _mock_release(monkeypatch, "", status=404)
    assert appdist.ensure_app(tmp_path, repo_url=repo, force=True) == "skipped: no release yet"


def test_ensure_app_verifies_the_manifest_checksum(tmp_path, monkeypatch):
    import hashlib

    repo = "https://github.com/Owner/Repo.git"
    exe = b"MZ" + b"\1" * 1_100_000
    good = {"version": "1.2.0-ccccccc", "sha256": hashlib.sha256(exe).hexdigest(), "size": len(exe)}
    _mock_release(monkeypatch, "ignored", exe=exe, manifest={**good, "sha256": "0" * 64})
    assert "checksum" in appdist.ensure_app(tmp_path, repo_url=repo, force=True)
    assert not (tmp_path / appdist.APP_FILE).exists()
    _mock_release(monkeypatch, "ignored", exe=exe, manifest={**good, "size": 5})
    assert "size" in appdist.ensure_app(tmp_path, repo_url=repo, force=True)
    _mock_release(monkeypatch, "ignored", exe=exe, manifest=good)
    assert appdist.ensure_app(tmp_path, repo_url=repo, force=True) == "updated: 1.2.0-ccccccc"
    assert (tmp_path / appdist.LOCAL_VERSION).read_text(encoding="utf-8") == "1.2.0-ccccccc"


def _client(tmp_path, monkeypatch, host="127.0.0.1"):
    from squad_vpn import agent
    from squad_vpn.api import create_app

    monkeypatch.setattr(agent, "project_root", lambda: tmp_path)
    app = create_app(tmp_path / "db.sqlite3", profiles_path=None, client_root=tmp_path)
    return TestClient(app, client=(host, 50000))


def test_app_page_and_local_controls(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert "SQUAD VPN" in client.get("/app").text
    assert client.get("/api/settings").json()["interval_minutes"] == 60
    saved = client.post("/api/settings", json={"interval_minutes": 30, "auto_update": False}).json()
    assert saved["interval_minutes"] == 30 and saved["restart_required"]
    assert client.post("/api/settings", json={"interval_minutes": 5}).status_code == 422
    logs = tmp_path / "data" / "logs"
    logs.mkdir(parents=True)
    (logs / "agent.log").write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert client.get("/api/logs", params={"name": "agent", "lines": 2}).json()["lines"] == ["two", "three"]
    assert client.get("/api/logs", params={"name": "../../etc/passwd"}).status_code == 422
    qr = client.get("/api/qr", params={"text": "https://example.com/sub"})
    assert qr.headers["content-type"].startswith("image/svg+xml") and b"<svg" in qr.content


def test_controls_are_refused_from_other_hosts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, host="192.168.1.50")
    for method, path in (
        ("get", "/api/settings"), ("post", "/api/control/restart"),
        ("get", "/api/logs"), ("post", "/api/autostart"),
    ):
        response = getattr(client, method)(path, json={}) if method == "post" else client.get(path)
        assert response.status_code == 403, path


def test_control_without_agent_reports_conflict(tmp_path, monkeypatch):
    from squad_vpn import agent

    monkeypatch.setattr(agent, "CONTROL_PORT", _free_port())
    monkeypatch.setattr(agent.send_command, "__defaults__", (agent.CONTROL_PORT,))
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/control/update").status_code == 409
    assert client.post("/api/control/format-disk").status_code == 422


def test_links_point_to_github(tmp_path, monkeypatch):
    from squad_vpn import publish

    monkeypatch.setattr(publish, "detect_origin", lambda *_: "https://github.com/Owner/Repo.git")
    client = _client(tmp_path, monkeypatch)
    links = client.get("/api/links").json()
    assert links["github_raw"] == "https://raw.githubusercontent.com/Owner/Repo/subs/"
    assert {p["name"] for p in links["profiles"]} >= {"balanced", "all"}


def _launcher():
    path = Path(__file__).resolve().parents[1] / "app" / "launcher.py"
    spec = importlib.util.spec_from_file_location("launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_pages_and_root():
    launcher = _launcher()
    assert (launcher.project_root() / "pyproject.toml").exists()
    html = launcher.page("Заголовок", "Текст", "<button>Ок</button>")
    assert "Заголовок" in html and "<button>Ок</button>" in html and "{" not in html.split("<style>")[0]
    assert launcher.APP_URL == "http://127.0.0.1:8080/app"


def test_launcher_js_api_exposes_only_methods(tmp_path):
    # pywebview walks public attributes recursively; a public window reference
    # froze the exe ("Не отвечает").
    launcher = _launcher()
    api = launcher.Api(tmp_path)
    api._window = object()
    public = {name: getattr(api, name) for name in dir(api) if not name.startswith("_")}
    assert public and all(callable(value) for value in public.values())


def test_launcher_escapes_messages():
    launcher = _launcher()
    html = launcher.page("<b>x</b>", "C:\\\\path<script>alert(1)</script>")
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_launcher_frameless_window_controls(tmp_path):
    # The window has no system frame: our title bar needs a drag region and
    # working minimize/close/place calls.
    launcher = _launcher()
    assert "pywebview-drag-region" in launcher.CHROME_JS
    calls = []

    class Window:
        def move(self, x, y):
            calls.append(("move", x, y))

        def resize(self, *args):
            calls.append(("resize", *args))

        def minimize(self):
            calls.append(("minimize",))

        def destroy(self):
            calls.append(("destroy",))

    api = launcher.Api(tmp_path)
    api._window = Window()
    api.window_place(10.4, 20, 1280, 720)
    api.window_minimize()
    api.window_close()
    assert calls == [("move", 10, 20), ("resize", 1280, 720), ("minimize",), ("destroy",)]
