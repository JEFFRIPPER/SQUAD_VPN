import json
import socket
import subprocess
import sys
import types
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from squad_vpn import agent as agent_module
from squad_vpn import ota
from squad_vpn.agent import Agent, _acquire_control_socket


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _repo(tmp_path):
    origin = tmp_path / "origin"
    (origin / "src" / "squad_vpn").mkdir(parents=True)
    _git(origin, "init", "-q", "-b", "main")
    (origin / "pyproject.toml").write_text("v1\n", encoding="utf-8")
    (origin / "src" / "squad_vpn" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "one")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    return origin, clone


def _push(origin, path, text, message="next"):
    (origin / path).parent.mkdir(parents=True, exist_ok=True)
    (origin / path).write_text(text, encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", message)
    return _git(origin, "rev-parse", "HEAD")


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def updater(tmp_path, monkeypatch):
    origin, clone = _repo(tmp_path)
    agent = Agent(clone, control_port=_free_port(), port=_free_port())
    agent.control = _acquire_control_socket(agent.control_port, wait_seconds=0)
    calls = {"popen": 0, "start_server": 0}

    class FakeChild:
        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(*args, **kwargs):
        calls["popen"] += 1
        return FakeChild()

    # Only the agent's own Popen is faked; git still runs for real.
    fake_subprocess = types.SimpleNamespace(**vars(subprocess))
    fake_subprocess.Popen = fake_popen
    monkeypatch.setattr(agent_module, "subprocess", fake_subprocess)
    monkeypatch.setattr(agent, "start_server", lambda: calls.__setitem__("start_server", calls["start_server"] + 1))
    monkeypatch.setattr(ota, "ci_verdict", lambda slug, sha: "success")
    monkeypatch.setattr(ota, "smoke_test", lambda root, python: (True, ""))
    monkeypatch.setattr(ota, "wait_healthy", lambda port, child, commit: True)
    yield origin, clone, agent, calls
    agent.control.close()


def _journal(clone):
    return json.loads((clone / "data" / "update.json").read_text(encoding="utf-8"))


def test_nothing_to_update(updater):
    _, clone, agent, calls = updater
    assert agent._maybe_update(agent.control) is False
    journal = _journal(clone)
    assert journal["message"] == "Установлена последняя версия"
    assert journal["last_check"] and journal["next_check"]
    assert calls["popen"] == 0


def test_update_that_failed_ci_is_skipped(updater, monkeypatch):
    origin, clone, agent, calls = updater
    head = _git(clone, "rev-parse", "HEAD")
    bad = _push(origin, "src/squad_vpn/x.py", "x = 1\n")
    monkeypatch.setattr(ota, "ci_verdict", lambda slug, sha: "failure")
    assert agent._maybe_update(agent.control) is False
    assert _git(clone, "rev-parse", "HEAD") == head
    journal = _journal(clone)
    assert bad in journal["skipped"]
    assert journal["history"][-1]["result"] == "skipped"
    # A later check does not retry the same bad commit.
    assert agent._maybe_update(agent.control) is False
    assert len(_journal(clone)["history"]) == 1


def test_update_waits_for_ci_then_gives_up_waiting(updater, monkeypatch):
    origin, clone, agent, calls = updater
    head = _git(clone, "rev-parse", "HEAD")
    new = _push(origin, "src/squad_vpn/x.py", "x = 1\n")
    monkeypatch.setattr(ota, "ci_verdict", lambda slug, sha: "pending")
    assert agent._maybe_update(agent.control) is False
    assert agent._retry_in == 600
    assert _git(clone, "rev-parse", "HEAD") == head
    # CI silent for too long: the update goes ahead (smoke test still guards it).
    journal = ota.Journal(clone)
    journal.data["pending"] = {
        "sha": new,
        "since": (datetime.now(UTC) - ota.CI_WAIT_LIMIT - timedelta(minutes=1)).isoformat(),
    }
    journal.save()
    assert agent._maybe_update(agent.control) is True
    assert _git(clone, "rev-parse", "HEAD") == new


def test_docs_only_update_needs_no_restart(updater):
    origin, clone, agent, calls = updater
    new = _push(origin, "README.md", "docs\n")
    assert agent._maybe_update(agent.control) is False
    assert _git(clone, "rev-parse", "HEAD") == new
    assert calls["popen"] == 0
    entry = _journal(clone)["history"][-1]
    assert entry["result"] == "ok" and entry["note"] == "без перезапуска"


def test_broken_update_is_rolled_back_before_restart(updater, monkeypatch):
    origin, clone, agent, calls = updater
    head = _git(clone, "rev-parse", "HEAD")
    bad = _push(origin, "src/squad_vpn/x.py", "def broken(:\n")
    monkeypatch.setattr(ota, "smoke_test", lambda root, python: (False, "SyntaxError"))
    assert agent._maybe_update(agent.control) is False
    assert _git(clone, "rev-parse", "HEAD") == head
    assert not (clone / "src" / "squad_vpn" / "x.py").exists()
    journal = _journal(clone)
    assert bad in journal["skipped"]
    assert journal["history"][-1]["result"] == "rolled_back"
    assert calls["popen"] == 0  # the running program was never stopped


def test_good_update_hands_over(updater):
    origin, clone, agent, calls = updater
    new = _push(origin, "src/squad_vpn/__init__.py", '__version__ = "9.9.9"\n')
    assert agent._maybe_update(agent.control) is True
    assert _git(clone, "rev-parse", "HEAD") == new
    entry = _journal(clone)["history"][-1]
    assert entry["result"] == "ok"
    assert entry["version_from"] != "9.9.9" and entry["version_to"] == "9.9.9"
    assert calls["popen"] == 1


def test_update_that_does_not_come_up_is_rolled_back(updater, monkeypatch):
    origin, clone, agent, calls = updater
    head = _git(clone, "rev-parse", "HEAD")
    _push(origin, "src/squad_vpn/x.py", "x = 2\n")
    monkeypatch.setattr(ota, "wait_healthy", lambda port, child, commit: False)
    old_control = agent.control
    assert agent._maybe_update(agent.control) is False
    assert _git(clone, "rev-parse", "HEAD") == head
    assert agent.control is not old_control  # control port taken back
    assert calls["start_server"] == 1  # the old version runs again
    assert _journal(clone)["history"][-1]["result"] == "rolled_back"


def test_git_head_reads_refs_without_git(tmp_path):
    _, clone = _repo(tmp_path)
    head = _git(clone, "rev-parse", "HEAD")
    assert ota.git_head(clone) == head
    _git(clone, "pack-refs", "--all")
    assert ota.git_head(clone) == head
    _git(clone, "checkout", "-q", "--detach")
    assert ota.git_head(clone) == head
    assert ota.git_head(tmp_path) is None


def test_needs_restart():
    assert ota.needs_restart(["src/squad_vpn/api.py"])
    assert ota.needs_restart(["pyproject.toml"])
    assert not ota.needs_restart(["README.md", "CHANGELOG.md", ".github/workflows/ci.yml"])
    assert not ota.needs_restart(["config/profiles.yaml"])  # re-read on the fly


def test_changelog_sections(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(
        "# История\n\n## 1.2.0 — OTA\n\n- one\n- two\n\n## 1.1.0 — red\n\ntext\n\n## 1.0.0\n\nold\n",
        encoding="utf-8",
    )
    sections = ota.changelog(tmp_path, 2)
    assert [s["title"] for s in sections] == ["1.2.0 — OTA", "1.1.0 — red"]
    assert sections[0]["text"] == "- one\n- two"


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([{"id": 1, "status": "completed", "conclusion": "success"}], "success"),
        ([{"id": 1, "status": "completed", "conclusion": "failure"}], "failure"),
        ([{"id": 1, "status": "in_progress", "conclusion": None}], "pending"),
        ([], "pending"),
        # A re-run that passed wins over the older failed run.
        (
            [
                {"id": 1, "status": "completed", "conclusion": "failure"},
                {"id": 2, "status": "completed", "conclusion": "success"},
            ],
            "success",
        ),
    ],
)
def test_ci_verdict(monkeypatch, runs, expected):
    def fake_get(url, **kwargs):
        assert kwargs["params"] == {"check_name": "test"}
        return httpx.Response(200, json={"check_runs": runs}, request=httpx.Request("GET", url))

    monkeypatch.setattr(ota.httpx, "get", fake_get)
    assert ota.ci_verdict("Owner/Repo", "a" * 40) == expected


def test_ci_verdict_unknown_without_network(monkeypatch):
    def offline(url, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(ota.httpx, "get", offline)
    assert ota.ci_verdict("Owner/Repo", "a" * 40) == "unknown"
    assert ota.ci_verdict(None, "a" * 40) == "unknown"


def test_smoke_test_runs_the_real_code(tmp_path, monkeypatch):
    ok, detail = ota.smoke_test(tmp_path, sys.executable)
    assert ok, detail
    monkeypatch.setattr(ota, "SMOKE_CODE", "raise SystemExit('boom')")
    ok, detail = ota.smoke_test(tmp_path, sys.executable)
    assert not ok and "boom" in detail


def test_update_status_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from squad_vpn.api import create_app

    journal = ota.Journal(tmp_path)
    journal.record("code", "ok", to="abc1234", version_to="1.2.0")
    journal.note("Установлена последняя версия")
    journal.save()
    (tmp_path / "CHANGELOG.md").write_text("## 1.2.0 — OTA\n\n- one\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path / "db.sqlite3", client_root=tmp_path))
    info = client.get("/api/update").json()
    assert info["message"] == "Установлена последняя версия"
    assert info["history"][0]["to"] == "abc1234"
    assert info["changelog"][0]["title"] == "1.2.0 — OTA"
    assert "commit" in client.get("/health").json()


def test_old_default_update_interval_follows_the_new_one(tmp_path):
    from squad_vpn.settings import load_settings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"update_hours": 3.0, "interval_minutes": 30}), encoding="utf-8")
    settings = load_settings(path)
    assert settings.update_hours == 1.0 and settings.interval_minutes == 30
    path.write_text(json.dumps({"update_hours": 6.0}), encoding="utf-8")
    assert load_settings(path).update_hours == 6.0
    path.write_text("[]", encoding="utf-8")
    assert load_settings(path).update_hours == 1.0
