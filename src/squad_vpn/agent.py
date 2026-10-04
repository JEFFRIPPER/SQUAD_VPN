"""Background agent: keeps SQUAD VPN running and up to date without user action.

- runs ``serve --watch`` (dashboard + hourly cycle) as a child process and
  restarts it if it dies;
- every hour pulls new code from GitHub (fast-forward only) over the air:
  only commits that passed CI, after a smoke test of the new code, and with
  an automatic rollback when the new version does not come up (``ota``);
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

from . import __version__, ota


CONTROL_PORT = 8079
STOP_COMMAND = b"stop"
# abort = stop without disconnecting the VPN (used to undo a failed update).
COMMANDS = {b"stop", b"update", b"restart", b"abort"}
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


def find_update(root: Path, branch: str = "main") -> tuple[str, str] | None:
    """``(head, remote)`` when ``origin/<branch>`` can be fast-forwarded to.

    ``None`` when there is nothing to do or the update is not safe (local
    commits, no network, not a git checkout).
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
    return head, remote


def apply_update(root: Path, head: str, remote: str) -> list[str] | None:
    """Fast-forward to ``remote``; the changed files, or ``None`` on conflict."""
    changed = _git(root, "diff", "--name-only", head, remote).stdout.split()
    merge = _git(root, "merge", "--ff-only", "--quiet", remote)
    if merge.returncode != 0:
        log.warning("Обновление не применено: %s", merge.stderr.strip()[-300:])
        return None
    log.info("Код обновлён %s -> %s (%d файлов)", head[:7], remote[:7], len(changed))
    return changed


def check_for_update(root: Path, branch: str = "main") -> list[str] | None:
    """Fast-forward the checkout to ``origin/<branch>``; the changed files."""
    found = find_update(root, branch)
    if found is None:
        return None
    return apply_update(root, *found)


def rollback(root: Path, commit: str) -> bool:
    """Return tracked files to ``commit``; untracked data/ is never touched."""
    result = _git(root, "reset", "--keep", "--quiet", commit)
    if result.returncode != 0:
        result = _git(root, "reset", "--hard", "--quiet", commit)
    if result.returncode != 0:
        log.error("Откат не удался: %s", result.stderr.strip()[-300:])
        return False
    log.warning("Откат на %s выполнен", commit[:7])
    return True


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
        update_hours: float = 1.0,
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
        self.control: socket.socket | None = None
        self._stopping = False
        # Seconds until the next check when an update is waiting for CI.
        self._retry_in: float | None = None
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

    def _agent_args(self) -> list[str]:
        return [sys.executable, "-m", "squad_vpn", "agent", *sys.argv[2:]]

    def _restart_self(self, control: socket.socket) -> None:
        """Start a fresh agent on the current code, then exit this one."""
        self.stop_server()
        control.close()
        subprocess.Popen(self._agent_args(), cwd=self.root, creationflags=NO_WINDOW, close_fds=True)
        log.info("Агент перезапускается")

    def _repo_slug(self) -> str | None:
        from .publish import GITHUB_URL, detect_origin

        match = GITHUB_URL.search(detect_origin(self.root) or "")
        return f"{match.group('owner')}/{match.group('repo')}" if match else None

    def _maybe_update(self, control: socket.socket) -> bool:
        """One over-the-air round. True when this agent handed over and must exit."""
        journal = ota.Journal(self.root)
        self._retry_in = None
        self.status["last_update_check"] = _now()
        try:
            return self._update_round(control, journal)
        finally:
            journal.checked(self._retry_in if self._retry_in is not None else self.update_seconds)
            journal.save()
            self._save_status()

    def _update_round(self, control: socket.socket, journal: ota.Journal) -> bool:
        found = find_update(self.root)
        if found is None:
            journal.note("Установлена последняя версия")
            return False
        head, remote = found
        if remote in journal.skipped:
            journal.note(f"Версия {remote[:7]} пропущена: {journal.skipped[remote]}")
            return False

        verdict = ota.ci_verdict(self._repo_slug(), remote)
        if verdict == "failure":
            journal.skip(remote, "не прошла проверки на GitHub")
            journal.record("code", "skipped", to=remote[:7], note="не прошла проверки на GitHub")
            journal.note(f"Версия {remote[:7]} не прошла проверки на GitHub — пропущена")
            log.warning("Версия %s не прошла CI, обновление пропущено", remote[:7])
            return False
        if verdict == "pending":
            waited = datetime.now(UTC) - journal.waiting_since(remote)
            if waited < ota.CI_WAIT_LIMIT:
                journal.note(f"Новая версия {remote[:7]} ещё проверяется на GitHub")
                self._retry_in = 600
                return False
        journal.data["pending"] = None

        old_version = __version__
        changed = apply_update(self.root, head, remote)
        if changed is None:
            journal.note("Обновление не применено: локальные изменения мешают")
            return False
        new_version = ota.version_on_disk(self.root) or "?"
        details = {
            "from": head[:7], "to": remote[:7],
            "version_from": old_version, "version_to": new_version,
        }
        self.status["commit"] = remote[:7]

        if not ota.needs_restart(changed):
            journal.record("code", "ok", **details, note="без перезапуска")
            journal.note(f"Обновлено до {remote[:7]}")
            return False

        deps_changed = "pyproject.toml" in changed
        problem = None
        if deps_changed and not reinstall(self.root):
            problem = "не установились зависимости"
        else:
            ok, detail = ota.smoke_test(self.root, sys.executable)
            if not ok:
                problem = f"новая версия не запускается: {detail[-300:]}"
        if problem is not None:
            self._undo(journal, head, remote, deps_changed, problem, details)
            return False

        self.status["last_update"] = _now()
        return self._handover(control, journal, head, remote, deps_changed, details)

    def _undo(
        self,
        journal: ota.Journal,
        head: str,
        remote: str,
        deps_changed: bool,
        problem: str,
        details: dict[str, object],
    ) -> None:
        rollback(self.root, head)
        if deps_changed:
            reinstall(self.root)
        self.status["commit"] = head[:7]
        journal.skip(remote, problem)
        journal.record("code", "rolled_back", **details, note=problem)
        journal.note(f"Версия {remote[:7]} откачена: {problem}")
        log.error("Обновление %s откачено: %s", remote[:7], problem)

    def _handover(
        self,
        control: socket.socket,
        journal: ota.Journal,
        head: str,
        remote: str,
        deps_changed: bool,
        details: dict[str, object],
    ) -> bool:
        """Start the agent on the new code; roll back if it does not come up."""
        self.stop_server()
        control.close()
        child = subprocess.Popen(
            self._agent_args(), cwd=self.root, creationflags=NO_WINDOW, close_fds=True
        )
        log.info("Запускаю новую версию %s и жду ответа…", remote[:7])
        if ota.wait_healthy(self.port, child, remote):
            journal.record("code", "ok", **details)
            journal.note(f"Обновлено до версии {details['version_to']} ({remote[:7]})")
            log.info("Новая версия %s работает, старый агент завершается", remote[:7])
            return True

        # The new version did not come up: stop it and bring the old one back.
        send_command("abort", self.control_port)
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            child.kill()
        self._undo(journal, head, remote, deps_changed, "новая версия не ответила после запуска", details)
        new_control = _acquire_control_socket(self.control_port, wait_seconds=60)
        if new_control is None:
            # Someone holds the port (a stuck new agent): let autostart sort it out.
            log.error("Не удалось вернуть управление после отката")
            return True
        self.control = new_control
        self.start_server()
        return False

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
        if result.startswith(("updated", "error")):
            journal = ota.Journal(self.root)
            if result.startswith("updated"):
                journal.record("app", "ok", to=result.split(":", 1)[1].strip())
            else:
                journal.record("app", "failed", note=result[7:200])
            journal.save()
        if result.startswith("updated"):
            from . import autostart

            try:
                if autostart.is_enabled():
                    autostart.ensure_shortcut(self.root, port=self.port)
            except OSError as exc:
                log.warning("Ярлык не обновлён: %s", exc)

    def run(self) -> int:
        self.control = _acquire_control_socket(self.control_port, wait_seconds=30)
        if self.control is None:
            log.info("Агент уже запущен — второй экземпляр не нужен")
            return 0
        log.info("Агент SQUAD VPN %s запущен в %s", __version__, self.root)
        self._save_status()
        ota.Journal(self.root).save()  # creates the file for the app on first start
        next_update = time.monotonic() + (60 if self.auto_update else float("inf"))
        next_app_check = time.monotonic() + 30
        restart_at: float | None = None
        try:
            self._apply_restore_request()
            self.start_server()
            while True:
                command = self._read_command(self.control)
                if command == b"stop":
                    log.info("Получена команда остановки")
                    self._stopping = True
                    break
                if command == b"abort":
                    log.info("Остановка по запросу прежней версии (откат обновления)")
                    break
                if command == b"restart":
                    log.info("Получена команда перезапуска")
                    self._restart_self(self.control)
                    return 0
                if command == b"update":
                    log.info("Проверка обновлений по запросу")
                    next_app_check = time.monotonic()
                    if self._maybe_update(self.control):
                        return 0
                    if self.auto_update:
                        next_update = time.monotonic() + (self._retry_in or self.update_seconds)
                if time.monotonic() >= next_app_check:
                    next_app_check = time.monotonic() + self.update_seconds
                    self._ensure_app()
                if (
                    restart_at is None
                    and self.child is not None
                    and self.child.poll() is not None
                ):
                    code = self.child.returncode
                    lived = time.monotonic() - self.child_started
                    self.backoff = 5.0 if lived > 600 else min(self.backoff * 2, 300.0)
                    log.warning(
                        "Сервер завершился (код %s), перезапуск через %.0f с", code, self.backoff
                    )
                    self.status["server_restarts"] = int(self.status["server_restarts"]) + 1  # type: ignore[call-overload]
                    self._save_status()
                    # No sleep here: commands (stop, abort) must work during the pause.
                    restart_at = time.monotonic() + self.backoff
                if restart_at is not None and time.monotonic() >= restart_at:
                    restart_at = None
                    self.start_server()
                if self.auto_update and time.monotonic() >= next_update:
                    if self._maybe_update(self.control):
                        return 0
                    next_update = time.monotonic() + (self._retry_in or self.update_seconds)
                time.sleep(2)
        except KeyboardInterrupt:
            log.info("Остановлено пользователем")
            self._stopping = True
        finally:
            self.stop_server()
            if self._stopping:
                self._cleanup_client()
            try:
                self.control.close()
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
