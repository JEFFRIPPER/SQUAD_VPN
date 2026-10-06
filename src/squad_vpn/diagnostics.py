"""«Проверить систему»: what works, what does not, and how to fix it."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx

from . import __version__


OK, WARN, ERROR = "ok", "warn", "error"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _check(id_: str, title: str, status: str, detail: str, fix: str | None = None) -> dict[str, object]:
    return {"id": id_, "title": title, "status": status, "detail": detail, "fix": fix}


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def run_checks(
    root: Path,
    database: Path,
    binary: Path,
    *,
    client_connected: bool = False,
    last_cycle: dict[str, object] | None = None,
    network: bool = True,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []

    version = sys.version_info
    checks.append(_check(
        "python", "Python", OK if version >= (3, 11) else ERROR,
        f"{version.major}.{version.minor}.{version.micro}, SQUAD VPN {__version__}",
    ))

    git = shutil.which("git")
    checks.append(_check(
        "git", "Git", OK if git else WARN,
        "найден" if git else "не найден: автообновление и сеть пробников не работают. Запусти install.cmd",
    ))

    if not Path(binary).exists():
        checks.append(_check("mihomo", "Ядро Mihomo", WARN,
                             "ещё не скачано — скачается при следующем обновлении серверов"))
    else:
        try:
            out = subprocess.run(
                [str(Path(binary).resolve()), "-v"], capture_output=True, text=True,
                timeout=10, creationflags=NO_WINDOW,
            ).stdout.strip().splitlines()
            checks.append(_check("mihomo", "Ядро Mihomo", OK, out[0] if out else "запускается"))
        except (OSError, subprocess.SubprocessError) as exc:
            checks.append(_check("mihomo", "Ядро Mihomo", ERROR, f"не запускается: {exc}"))

    try:
        connection = sqlite3.connect(database, timeout=10)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()[0]
            nodes = connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            alive = connection.execute("SELECT COUNT(*) FROM nodes WHERE alive = 1").fetchone()[0]
        finally:
            connection.close()
        size = Path(database).stat().st_size / 1_000_000
        status = OK if result == "ok" else ERROR
        detail = f"серверов {nodes}, живых {alive}, {size:.1f} МБ" if status == OK else f"повреждена: {result}"
        checks.append(_check("database", "База серверов", status, detail,
                             None if status == OK else "restore_backup"))
    except (sqlite3.Error, OSError) as exc:
        checks.append(_check("database", "База серверов", ERROR, str(exc), "restore_backup"))

    free = shutil.disk_usage(root).free / 1_000_000
    checks.append(_check(
        "disk", "Свободное место", OK if free >= 300 else WARN if free >= 100 else ERROR,
        f"{free:.0f} МБ",
    ))

    agent_running = _port_open(8079)
    checks.append(_check(
        "agent", "Фоновая программа", OK if agent_running else WARN,
        "работает" if agent_running else "не запущена: серверы не обновляются сами. Запусти SQUAD VPN.exe",
    ))

    if last_cycle is not None:
        if not last_cycle:
            checks.append(_check("cycle", "Обновление серверов", WARN, "ещё не запускалось"))
        else:
            errors = last_cycle.get("errors") or []
            checks.append(_check(
                "cycle", "Обновление серверов", OK if not errors else WARN,
                f"последнее {last_cycle.get('finished_at', '?')}"
                + (f"; ошибки: {'; '.join(map(str, errors))[:300]}" if errors else ""),
            ))

    try:
        probe = json.loads((root / "data" / "probe.json").read_text(encoding="utf-8"))
        region = probe.get("region", "??")
        checks.append(_check(
            "probe", "Пробник", OK if region != "??" else WARN,
            f"{probe.get('probe_id')} ({region})"
            + ("" if region != "??" else " — страна не определилась, укажи её в настройках"),
        ))
    except (OSError, ValueError):
        checks.append(_check("probe", "Пробник", WARN, "ещё не создан — появится после первого цикла"))

    if os.name == "nt":
        from . import sysproxy
        from .client import MIXED_PORT

        try:
            state = sysproxy.default_backend().read()
            ours = sysproxy.ours(state, MIXED_PORT)
            if ours and not client_connected:
                checks.append(_check(
                    "proxy", "Системный прокси", ERROR,
                    "указывает на SQUAD VPN, но VPN не подключён — интернет может не работать",
                    "restore_proxy",
                ))
            else:
                checks.append(_check(
                    "proxy", "Системный прокси", OK,
                    "SQUAD VPN" if ours else (state.server if state.enabled else "выключен"),
                ))
        except OSError as exc:
            checks.append(_check("proxy", "Системный прокси", WARN, str(exc)))

    from .backup import list_backups

    backups = list_backups(root / "data" / "backups")
    if not backups:
        checks.append(_check("backup", "Резервные копии", WARN, "ещё нет", "backup_now"))
    else:
        newest = root / "data" / "backups" / str(backups[0]["name"])
        age = (time.time() - newest.stat().st_mtime) / 3600
        checks.append(_check(
            "backup", "Резервные копии", OK if age < 72 else WARN,
            f"{len(backups)} шт., последняя {age:.0f} ч назад", None if age < 72 else "backup_now",
        ))

    if network:
        try:
            with httpx.Client(timeout=6.0, trust_env=False, follow_redirects=True) as client:
                client.head("https://github.com")
            checks.append(_check("github", "Связь с GitHub", OK, "есть"))
        except httpx.HTTPError as exc:
            checks.append(_check(
                "github", "Связь с GitHub", WARN,
                f"нет ({type(exc).__name__}): не работают обновления и обмен отчётами пробников",
            ))
    return checks
