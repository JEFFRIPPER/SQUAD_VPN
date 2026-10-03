"""Background agent: keeps SQUAD VPN running and up to date without user action.

- runs ``serve --watch`` (dashboard + hourly cycle) as a child process and
  restarts it if it dies;
- every few hours pulls new code from GitHub (fast-forward only), reinstalls
  dependencies when ``pyproject.toml`` changed and restarts itself;
- only one agent runs at a time; ``squad-vpn agent --stop`` stops it;
- logs to ``data/logs`` because under ``pythonw`` there is no console.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__


CONTROL_PORT = 8079
STOP_COMMAND = b"stop"
COMMANDS = {b"stop", b"update", b"restart"}
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

log = logging.getLogger("squad_vpn.agent")


def project_root() -> Path:
    """The git checkout this package runs from (editable install), else cwd."""
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


def setup_logging(root: Path) -> None:
    logs = root / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        logs / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    if sys.stdout is not None:
        log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)


def _git(root: Path, *args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=NO_WINDOW,
    )


DEFAULT_REPO = "https://github.com/JEFFRIPPER/SQUAD_VPN.git"


def ensure_git_checkout(root: Path, repo: str = DEFAULT_REPO) -> bool:
    """Turn a copy installed from a zip into a git checkout of ``repo``.

    Files stay as they are; git just starts tracking them, so the regular
    fast-forward update works from then on.
    """
    import shutil

    if (root / ".git").exists():
        return True
    if shutil.which("git") is None or not (root / "pyproject.toml").exists():
        return False
    steps = [
        ("init", "-q"),
        ("remote", "add", "origin", repo),
        ("fetch", "-q", "--depth", "50", "origin", "main"),
        ("reset", "-q", "origin/main"),
        ("branch", "-q", "-M", "main"),
    ]
    for step in steps:
        result = _git(root, *step)
        if result.returncode != 0:
            log.warning("Не удалось подключить git (%s): %s", step[0], result.stderr.strip()[-300:])
            return False
    log.info("Папка подключена к GitHub — автообновление включено")
    return True


def check_for_update(root: Path, branch: str = "main") -> list[str] | None:
    """Fast-forward the checkout to ``origin/<branch>``.

    Returns the list of changed files when the code was updated, ``None``
    when there is nothing to do or the update is not safe (local commits,
    conflicting local edits, no network).
    """
    if not (root / ".git").exists() and not ensure_git_checkout(root):
        log.info("Не git-репозиторий, автообновление пропущено")
        return None
    fetch = _git(root, "fetch", "--quiet", "origin", branch)
    if fetch.returncode != 0:
        log.warning("git fetch не удался: %s", fetch.stderr.strip()[-300:])
        return None
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    remote = _git(root, "rev-parse", f"origin/{branch}").stdout.strip()
    if not head or not remote or head == remote:
        return None
    if _git(root, "merge-base", "--is-ancestor", "HEAD", f"origin/{branch}").returncode != 0:
        log.warning("Есть локальные коммиты, которых нет на GitHub: автообновление пропущено")
        return None
    changed = _git(root, "diff", "--name-only", head, remote).stdout.split()
    merge = _git(root, "merge", "--ff-only", "--quiet", f"origin/{branch}")
    if merge.returncode != 0:
        log.warning("Обновление не применено: %s", merge.stderr.strip()[-300:])
        return None
    log.info("Код обновлён %s -> %s (%d файлов)", head[:7], remote[:7], len(changed))
    return changed


def reinstall(root: Path) -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-e", "."],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    )
    if result.returncode != 0:
        log.error("pip install не удался: %s", result.stderr.strip()[-500:])
        return False
    log.info("Зависимости обновлены")
    return True


def send_command(command: str, port: int = CONTROL_PORT) -> bool:
    """Send stop / update / restart to the running agent."""
    if command.encode() not in COMMANDS:
        raise ValueError(f"Неизвестная команда: {command}")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3) as conn:
            conn.sendall(command.encode())
        return True
    except OSError:
        return False


def request_stop(port: int = CONTROL_PORT) -> bool:
    return send_command("stop", port)


def _acquire_control_socket(port: int, wait_seconds: float) -> socket.socket | None:
    """Bind the control port: it is both the single-instance lock and the stop channel."""
    deadline = time.monotonic() + wait_seconds
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
            sock.listen(4)
            sock.setblocking(False)
            return sock
        except OSError:
            sock.close()
            if time.monotonic() >= deadline:
                return None
            time.sleep(1)


class Agent:
    def __init__(
        self,
        root: Path,
        *,
        port: int = 8080,
        interval_minutes: int = 60,
        update_hours: float = 3.0,
        auto_update: bool = True,
        control_port: int = CONTROL_PORT,
    ) -> None:
        self.root = root
        self.port = port
        self.interval_minutes = interval_minutes
        self.update_seconds = max(0.1, update_hours) * 3600
        self.auto_update = auto_update
        self.control_port = control_port
        self.child: subprocess.Popen[bytes] | None = None
        self._stopping = False
        self.child_started = 0.0
        self.backoff = 5.0
        self.status_path = root / "data" / "agent.json"
        self.status: dict[str, object] = {
            "pid": os.getpid(),
            "version": __version__,
            "started_at": _now(),
            "auto_update": auto_update,
            "commit": self._commit(),
            "last_update_check": None,
            "last_update": None,
            "server_restarts": 0,
        }

    def _commit(self) -> str | None:
        try:
            result = _git(self.root, "rev-parse", "--short", "HEAD", timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() or None

    def _save_status(self) -> None:
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            self.status_path.write_text(
                json.dumps(self.status, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def _server_command(self) -> list[str]:
        from .keys import KeyStore
        from .settings import load_settings

        command = [
            sys.executable, "-m", "squad_vpn", "serve", "--watch", "--probe-publish",
            "--port", str(self.port),
            "--interval-minutes", str(self.interval_minutes),
        ]
        # Open to the local network only when there is a key to protect it.
        if load_settings(self.root / "data" / "settings.json").lan_access and KeyStore(
            self.root / "data" / "api_keys.json"
        ).load():
            command += ["--host", "0.0.0.0"]
        return command

    def _apply_restore_request(self) -> None:
        """Restore a backup chosen in the app, before the server opens the DB."""
        from .backup import restore_backup

        request = self.root / "data" / "restore-request.json"
        if not request.exists():
            return
        try:
            name = json.loads(request.read_text(encoding="utf-8"))["name"]
            restore_backup(name, self.root / "data" / "squad_vpn.sqlite3", self.root / "data" / "backups")
            log.info("База восстановлена из копии %s", name)
        except Exception as exc:
            log.error("Не удалось восстановить копию: %s", exc)
        finally:
            request.unlink(missing_ok=True)

    def start_server(self) -> None:
        logs = self.root / "data" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        server_log = logs / "server.log"
        if server_log.exists() and server_log.stat().st_size > 5_000_000:
            server_log.replace(logs / "server.log.1")
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        with open(server_log, "ab") as output:
            self.child = subprocess.Popen(
                self._server_command(),
                cwd=self.root,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=NO_WINDOW,
            )
        self.child_started = time.monotonic()
        log.info("Сервер запущен (pid %s): http://127.0.0.1:%s/", self.child.pid, self.port)

    def stop_server(self) -> None:
        if self.child is None or self.child.poll() is not None:
            return
        self.child.terminate()
        try:
            self.child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=5)
        log.info("Сервер остановлен")

    def _restart_self(self, control: socket.socket) -> None:
        """Start a fresh agent on the new code, then exit this one."""
        self.stop_server()
        control.close()
        args = [sys.executable, "-m", "squad_vpn", "agent", *sys.argv[2:]]
        subprocess.Popen(args, cwd=self.root, creationflags=NO_WINDOW, close_fds=True)
        log.info("Агент перезапускается на новой версии")

    def _maybe_update(self, control: socket.socket) -> bool:
        self.status["last_update_check"] = _now()
        changed = check_for_update(self.root)
        self._save_status()
        if changed is None:
            return False
        if "pyproject.toml" in changed:
            reinstall(self.root)
        self.status["last_update"] = _now()
        self._save_status()
        self._restart_self(control)
        return True

    def _read_command(self, control: socket.socket) -> bytes | None:
        try:
            conn, _ = control.accept()
        except (BlockingIOError, OSError):
            return None
        with conn:
            conn.settimeout(2)
            try:
                command = conn.recv(16).strip()
            except OSError:
                return None
        return command if command in COMMANDS else None

    def _cleanup_client(self) -> None:
        """The server was killed without a chance to disconnect: undo the
        system proxy ourselves so the computer keeps its internet."""
        from .client import cleanup_orphan

        try:
            result = cleanup_orphan(self.root, clear_resume=True)
            if any(result.values()):
                log.info("VPN-клиент отключён: %s", result)
        except Exception as exc:
            log.warning("Не удалось отключить VPN-клиент: %s", exc)

    def _ensure_app(self) -> None:
        from .appdist import ensure_app

        try:
            result = ensure_app(self.root)
        except Exception as exc:  # the app is optional; never break the agent
            result = f"error: {exc}"
        self.status["app"] = result
        self.status["app_checked"] = _now()
        self._save_status()
        if result.startswith("error"):
            log.warning("Приложение не обновлено: %s", result)
        if result.startswith("updated"):
            from . import autostart

            try:
                if autostart.is_enabled():
                    autostart.ensure_shortcut(self.root, port=self.port)
            except OSError as exc:
                log.warning("Ярлык не обновлён: %s", exc)

    def run(self) -> int:
        control = _acquire_control_socket(self.control_port, wait_seconds=30)
        if control is None:
            log.info("Агент уже запущен — второй экземпляр не нужен")
            return 0
        log.info("Агент SQUAD VPN %s запущен в %s", __version__, self.root)
        self._save_status()
        next_update = time.monotonic() + (60 if self.auto_update else float("inf"))
        next_app_check = time.monotonic() + 30
        try:
            self._apply_restore_request()
            self.start_server()
            while True:
                command = self._read_command(control)
                if command == b"stop":
                    log.info("Получена команда остановки")
                    self._stopping = True
                    break
                if command == b"restart":
                    log.info("Получена команда перезапуска")
                    self._restart_self(control)
                    return 0
                if command == b"update":
                    log.info("Проверка обновлений по запросу")
                    next_app_check = time.monotonic()
                    if self._maybe_update(control):
                        return 0
                if time.monotonic() >= next_app_check:
                    next_app_check = time.monotonic() + self.update_seconds
                    self._ensure_app()
                if self.child is not None and self.child.poll() is not None:
                    code = self.child.returncode
                    lived = time.monotonic() - self.child_started
                    self.backoff = 5.0 if lived > 600 else min(self.backoff * 2, 300.0)
                    log.warning(
                        "Сервер завершился (код %s), перезапуск через %.0f с", code, self.backoff
                    )
                    self.status["server_restarts"] = int(self.status["server_restarts"]) + 1  # type: ignore[call-overload]
                    self._save_status()
                    time.sleep(self.backoff)
                    self.start_server()
                if self.auto_update and time.monotonic() >= next_update:
                    next_update = time.monotonic() + self.update_seconds
                    if self._maybe_update(control):
                        return 0
                time.sleep(2)
        except KeyboardInterrupt:
            log.info("Остановлено пользователем")
            self._stopping = True
        finally:
            self.stop_server()
            if self._stopping:
                self._cleanup_client()
            try:
                control.close()
            except OSError:
                pass
        return 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def read_status(root: Path | None = None) -> dict[str, object] | None:
    path = (root or project_root()) / "data" / "agent.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
