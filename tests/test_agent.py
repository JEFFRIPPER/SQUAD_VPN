import socket
import subprocess

from squad_vpn.agent import _acquire_control_socket, check_for_update, request_stop


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _setup(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "pyproject.toml").write_text("v1\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "one")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    return origin, clone


def test_update_fast_forwards(tmp_path):
    origin, clone = _setup(tmp_path)
    assert check_for_update(clone) is None
    (origin / "pyproject.toml").write_text("v2\n", encoding="utf-8")
    (origin / "new.py").write_text("x = 1\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "two")
    changed = check_for_update(clone)
    assert sorted(changed) == ["new.py", "pyproject.toml"]
    assert (clone / "new.py").exists()
    assert _git(clone, "rev-parse", "HEAD") == _git(origin, "rev-parse", "HEAD")


def test_update_skipped_with_local_commits(tmp_path):
    origin, clone = _setup(tmp_path)
    (clone / "local.txt").write_text("mine\n", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "local")
    (origin / "remote.txt").write_text("theirs\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "remote")
    assert check_for_update(clone) is None
    assert (clone / "local.txt").exists()


def test_update_skipped_when_local_edit_conflicts(tmp_path):
    origin, clone = _setup(tmp_path)
    (clone / "pyproject.toml").write_text("local edit\n", encoding="utf-8")
    (origin / "pyproject.toml").write_text("v2\n", encoding="utf-8")
    _git(origin, "commit", "-q", "-am", "two")
    assert check_for_update(clone) is None
    assert (clone / "pyproject.toml").read_text(encoding="utf-8") == "local edit\n"


def test_update_skipped_outside_git(tmp_path):
    assert check_for_update(tmp_path) is None


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_control_socket_is_single_instance_and_accepts_stop(tmp_path):
    port = _free_port()
    first = _acquire_control_socket(port, wait_seconds=0)
    try:
        assert first is not None
        assert _acquire_control_socket(port, wait_seconds=0) is None
        assert request_stop(port) is True
    finally:
        first.close()
    assert request_stop(port) is False


def test_startup_script_quotes_paths():
    from pathlib import PureWindowsPath

    from squad_vpn.autostart import shortcut_body, startup_script

    script = startup_script(
        PureWindowsPath(r'D:\CODE PROECTS\SQUAD_VPN'),
        PureWindowsPath(r'D:\CODE PROECTS\SQUAD_VPN\.venv\Scripts\pythonw.exe'),
    )
    assert 'shell.CurrentDirectory = "D:\\CODE PROECTS\\SQUAD_VPN"' in script
    assert 'shell.Run """D:\\CODE PROECTS\\SQUAD_VPN\\.venv\\Scripts\\pythonw.exe"" -m squad_vpn agent", 0, False' in script
    assert "URL=http://127.0.0.1:8080/" in shortcut_body()


def test_autostart_enable_and_disable(tmp_path, monkeypatch):
    import os

    import pytest

    from squad_vpn import autostart

    if os.name != "nt":
        with pytest.raises(OSError):
            autostart.enable(tmp_path)
        return
    folders = {autostart.CSIDL_STARTUP: tmp_path / "startup", autostart.CSIDL_DESKTOPDIRECTORY: tmp_path / "desktop"}
    for folder in folders.values():
        folder.mkdir()
    monkeypatch.setattr(autostart, "_known_folder", lambda csidl: folders[csidl])
    created = autostart.enable(tmp_path)
    assert all(path.exists() for path in created)
    assert "squad_vpn agent" in created[0].read_text(encoding="utf-16")
    assert len(autostart.disable()) >= 2
    assert not any(path.exists() for path in created)


def test_zip_copy_becomes_git_checkout(tmp_path):
    from squad_vpn.agent import ensure_git_checkout

    origin, _ = _setup(tmp_path)
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "pyproject.toml").write_text("v1\n", encoding="utf-8")
    (copy / "local-data.txt").write_text("keep me\n", encoding="utf-8")
    assert ensure_git_checkout(copy, repo=str(origin)) is True
    assert (copy / ".git").exists()
    assert _git(copy, "rev-parse", "HEAD") == _git(origin, "rev-parse", "HEAD")
    assert (copy / "local-data.txt").read_text(encoding="utf-8") == "keep me\n"
    (origin / "new.py").write_text("x = 1\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "two")
    assert check_for_update(copy) == ["new.py"]
