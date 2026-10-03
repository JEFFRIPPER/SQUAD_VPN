import asyncio
import subprocess

import pytest
from fastapi.testclient import TestClient

from squad_vpn.cycle import CycleOptions, run_cycle
from squad_vpn.models import ProxyNode, ValidationResult
from squad_vpn.publish import PublishError, PublishTarget, publish
from squad_vpn.store import NodeStore


def _age(store, fingerprint, column, delta):
    store.connection.execute(
        f"UPDATE nodes SET {column} = datetime('now', ?) WHERE fingerprint = ?",
        (delta, fingerprint),
    )
    store.connection.commit()


def test_cleanup_removes_only_nodes_gone_from_sources(tmp_path):
    store = NodeStore(tmp_path / "clean.sqlite3")
    try:
        gone = ProxyNode("vless", "gone.example", 443, raw_uri="a")
        dead_gone = ProxyNode("vless", "deadgone.example", 443, raw_uri="b")
        dead_present = ProxyNode("vless", "deadhere.example", 443, raw_uri="c")
        alive = ProxyNode("vless", "alive.example", 443, raw_uri="d")
        store.upsert_many([gone, dead_gone, dead_present, alive])
        for node in (dead_gone, dead_present):
            store.record_validation(ValidationResult(node.fingerprint, False, error="x"))
        store.record_validation(ValidationResult(alive.fingerprint, True, latency_ms=50))
        _age(store, gone.fingerprint, "last_seen", "-5 days")
        _age(store, dead_gone.fingerprint, "last_seen", "-30 hours")

        removed = store.cleanup(unseen_days=3, dead_unseen_hours=24)
        assert removed == {"unseen": 1, "dead_unseen": 1, "total": 2}
        left = {node.host for node in store.list_nodes()}
        assert left == {"deadhere.example", "alive.example"}
        orphans = store.connection.execute(
            "SELECT COUNT(*) FROM health_checks WHERE fingerprint = ?",
            (dead_gone.fingerprint,),
        ).fetchone()[0]
        assert orphans == 0
    finally:
        store.close()


def test_dead_nodes_are_rechecked_less_often(tmp_path):
    store = NodeStore(tmp_path / "backoff.sqlite3")
    try:
        dead = ProxyNode("vless", "dead.example", 443, raw_uri="a")
        alive = ProxyNode("vless", "alive.example", 443, raw_uri="b")
        store.upsert_many([dead, alive])
        store.record_validation(ValidationResult(dead.fingerprint, False, error="x"))
        store.record_validation(ValidationResult(alive.fingerprint, True, latency_ms=50))
        _age(store, dead.fingerprint, "last_checked", "-2 hours")
        _age(store, alive.fingerprint, "last_checked", "-2 hours")
        picked = {n.host for n in store.list_validation_candidates(recheck_after_minutes=60)}
        assert picked == {"alive.example"}
        _age(store, dead.fingerprint, "last_checked", "-7 hours")
        picked = {n.host for n in store.list_validation_candidates(recheck_after_minutes=60)}
        assert picked == {"alive.example", "dead.example"}
    finally:
        store.close()


def test_last_alive_is_tracked(tmp_path):
    store = NodeStore(tmp_path / "alive.sqlite3")
    try:
        node = ProxyNode("vless", "n.example", 443, raw_uri="a")
        store.upsert_many([node])
        store.record_validation(ValidationResult(node.fingerprint, True, latency_ms=50))
        first = store.connection.execute("SELECT last_alive FROM nodes").fetchone()[0]
        store.record_validation(ValidationResult(node.fingerprint, False, error="x"))
        after = store.connection.execute("SELECT last_alive FROM nodes").fetchone()[0]
        assert first is not None and after == first
    finally:
        store.close()


def _seed_alive(database):
    store = NodeStore(database)
    try:
        node = ProxyNode(
            "trojan", "fast.example", 443, userinfo="pw",
            raw_uri="trojan://pw@fast.example:443#Fast",
        )
        store.upsert_many([node])
        for latency in (80, 90, 85):
            store.record_validation(
                ValidationResult(node.fingerprint, True, latency_ms=latency, country="DE")
            )
        return node
    finally:
        store.close()


def _bare_repo(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    return remote


def _branch_files(remote, branch):
    out = subprocess.run(
        ["git", "--git-dir", str(remote), "ls-tree", "-r", "--name-only", branch],
        check=True, capture_output=True, text=True,
    ).stdout
    return set(out.split())


def _show(remote, branch, path):
    return subprocess.run(
        ["git", "--git-dir", str(remote), "show", f"{branch}:{path}"],
        check=True, capture_output=True, text=True,
    ).stdout


def test_publish_force_pushes_single_commit(tmp_path):
    import base64

    node = _seed_alive(tmp_path / "pub.sqlite3")
    remote = _bare_repo(tmp_path)
    target = PublishTarget(str(remote), branch="subs", workdir=tmp_path / "work")
    store = NodeStore(tmp_path / "pub.sqlite3")
    try:
        result = publish(store, target)
        publish(store, target)
    finally:
        store.close()

    files = _branch_files(remote, "subs")
    assert {"README.md", "stats.json", "balanced", "balanced.b64", "balanced.yaml",
            "all.b64", "country/DE.b64", "protocol/trojan.b64", "index.json"} <= files
    assert base64.b64decode(_show(remote, "subs", "fast.b64")).decode().strip() == node.raw_uri
    commits = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-list", "--count", "subs"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert commits == "1"
    assert result["profiles"]["fast"] == 1


def test_publish_builds_github_links(tmp_path):
    target = PublishTarget("https://x-access-token:SECRET@github.com/Owner/Repo.git", branch="subs")
    assert target.raw_base() == "https://raw.githubusercontent.com/Owner/Repo/subs/"
    assert target.cdn_base() == "https://cdn.jsdelivr.net/gh/Owner/Repo@subs/"
    assert PublishTarget("git@github.com:Owner/Repo.git").github() == ("Owner", "Repo")


def test_publish_refuses_main_branch(tmp_path):
    store = NodeStore(tmp_path / "x.sqlite3")
    try:
        with pytest.raises(PublishError):
            publish(store, PublishTarget(str(tmp_path / "r.git"), branch="main"))
    finally:
        store.close()


def test_publish_error_hides_credentials(tmp_path):
    store = NodeStore(tmp_path / "x.sqlite3")
    try:
        target = PublishTarget(
            "https://user:SECRET@127.0.0.1:9/repo.git", branch="subs", workdir=tmp_path / "w"
        )
        with pytest.raises(PublishError) as info:
            publish(store, target)
        assert "SECRET" not in str(info.value)
    finally:
        store.close()


def test_cycle_survives_failing_steps_and_still_exports(tmp_path):
    database = tmp_path / "cycle.sqlite3"
    _seed_alive(database)
    sources = tmp_path / "sources.yaml"
    sources.write_text("sources:\n  - name: down\n    url: http://127.0.0.1:9/x\n", encoding="utf-8")
    remote = _bare_repo(tmp_path)
    options = CycleOptions(
        sources=sources,
        database=database,
        output=tmp_path / "out",
        binary=tmp_path / "missing-mihomo",
        install_mihomo=False,
        publish=PublishTarget(str(remote), branch="subs", workdir=tmp_path / "work"),
    )
    logs = []
    report = asyncio.run(run_cycle(options, log=logs.append))
    assert set(report.steps) == {"collect", "validate", "cleanup", "export", "publish"}
    assert not report.ok
    assert any(error.startswith("validate:") for error in report.errors)
    assert report.steps["collect"]["ok"] == 0
    assert report.steps["export"]["profiles"]["fast"] == 1
    assert (tmp_path / "out" / "smart" / "fast.b64").exists()
    assert "fast.b64" in _branch_files(remote, "subs")


def test_api_cycle_status(tmp_path):
    from squad_vpn.api import create_app

    database = tmp_path / "api.sqlite3"
    _seed_alive(database)
    off = TestClient(create_app(database))
    assert off.get("/api/cycle").json() == {"enabled": False}
    assert off.post("/api/cycle/run").status_code == 409

    options = CycleOptions(
        sources=tmp_path / "none.yaml",
        database=database,
        output=tmp_path / "out",
        binary=tmp_path / "missing",
        install_mihomo=False,
    )
    (tmp_path / "none.yaml").write_text("sources: []\n", encoding="utf-8")
    with TestClient(create_app(database, cycle=options, interval_minutes=60)) as client:
        for _ in range(100):
            status = client.get("/api/cycle").json()
            if status["last"] is not None:
                break
            import time
            time.sleep(0.05)
        assert status["enabled"] is True
        assert status["last"]["steps"]["export"]["profiles"]["fast"] == 1
        assert client.post("/api/cycle/run").json()["started"] in (True, False)
