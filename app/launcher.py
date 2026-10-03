"""SQUAD VPN.exe — desktop window for the SQUAD VPN control panel.

The exe is a thin shell: it lives in the project folder, makes sure the
background agent runs (or offers to install it) and shows the panel served
by the agent at http://127.0.0.1:8080/app. The panel itself comes from the
project code, so it updates together with the project without a new exe.

Only the standard library and pywebview are used here on purpose.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


PORT = 8080
BASE = f"http://127.0.0.1:{PORT}"
APP_URL = f"{BASE}/app"
TITLE = "SQUAD VPN"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
NEW_CONSOLE = 0x00000010  # CREATE_NEW_CONSOLE


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def healthy(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=timeout) as response:
            return json.loads(response.read().decode()).get("status") == "ok"
    except (OSError, ValueError):
        return False


def wait_healthy(seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if healthy():
            return True
        time.sleep(1)
    return False


def start_agent(root: Path) -> None:
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    subprocess.Popen(
        [str(pythonw), "-m", "squad_vpn", "agent"],
        cwd=root,
        creationflags=NO_WINDOW,
        close_fds=True,
    )


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<style>
:root {{ --p:#4355B9; --op:#fff; --s:#FBF8FF; --os:#1B1B21; --v:#46464F; --c:#DEE0FF; }}
@media (prefers-color-scheme: dark) {{ :root {{ --p:#BAC3FF; --op:#08218A; --s:#121318; --os:#E4E1E9; --v:#C6C5D0; --c:#293CA0; }} }}
html,body {{ height:100%; margin:0; }}
body {{ background:var(--s); color:var(--os); font:14px/20px "Segoe UI",Roboto,system-ui,sans-serif;
  display:grid; place-items:center; text-align:center; padding:24px; box-sizing:border-box; }}
.logo {{ width:96px; height:96px; border-radius:28px; background:var(--c); display:grid; place-items:center; margin:0 auto 24px; }}
h1 {{ font-size:28px; line-height:36px; font-weight:400; margin:0 0 8px; }}
p {{ color:var(--v); max-width:440px; margin:0 auto 24px; }}
.spinner {{ width:40px; height:40px; border-radius:50%; border:4px solid var(--p); border-right-color:transparent;
  animation:spin .9s linear infinite; margin:0 auto; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
button {{ height:40px; padding:0 24px; border-radius:20px; border:0; background:var(--p); color:var(--op);
  font:500 14px "Segoe UI",Roboto,sans-serif; cursor:pointer; margin:4px; }}
button.alt {{ background:transparent; color:var(--p); border:1px solid var(--v); }}
</style></head><body><div>
<div class="logo"><svg width="48" height="48" viewBox="0 0 24 24"><path fill="var(--p)"
 d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5zm-1.5 14.5-4-4 1.4-1.4 2.6 2.6 5.6-5.6 1.4 1.4z"/></svg></div>
<h1>{title}</h1><p>{text}</p>{body}</div></body></html>"""


def page(title: str, text: str, body: str = '<div class="spinner"></div>') -> str:
    return PAGE.format(title=title, text=text, body=body)


class Api:
    """Functions callable from the splash pages (window.pywebview.api.*)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.window = None

    def install(self) -> None:
        installer = self.root / "install.cmd"
        subprocess.Popen(["cmd", "/c", str(installer)], cwd=self.root, creationflags=NEW_CONSOLE)
        self.window.load_html(page(
            "Устанавливаю…",
            "Открылось окно установки: дождись слова Done. Это окно само переключится на панель.",
        ))
        threading.Thread(target=self._after_install, daemon=True).start()

    def _after_install(self) -> None:
        if wait_healthy(900):
            self.window.load_url(APP_URL)
        else:
            show_error(self.window, self.root, "Установка не завершилась",
                       "Посмотри окно установки: если там ошибка, пришли её текст.")

    def retry(self) -> None:
        threading.Thread(target=boot, args=(self.window, self.root), daemon=True).start()

    def open_logs(self) -> None:
        folder = self.root / "data" / "logs"
        os.startfile(folder if folder.exists() else self.root)  # type: ignore[attr-defined]


def show_error(window, root: Path, title: str, text: str) -> None:
    window.load_html(page(
        title,
        text,
        '<button onclick="pywebview.api.retry()">Повторить</button>'
        '<button class="alt" onclick="pywebview.api.open_logs()">Открыть журнал</button>',
    ))


def boot(window, root: Path) -> None:
    if not (root / "pyproject.toml").exists():
        window.load_html(page(
            "Не та папка",
            f"Положи «SQUAD VPN.exe» в папку проекта SQUAD VPN (где лежит install.cmd). "
            f"Сейчас он в {root}.",
            "",
        ))
        return
    if healthy():
        window.load_url(APP_URL)
        return
    if not (root / ".venv" / "Scripts" / "pythonw.exe").exists():
        window.load_html(page(
            "SQUAD VPN ещё не установлен",
            "Установка займёт пару минут и делается один раз: Python, зависимости, "
            "автозапуск. Дальше всё работает само.",
            '<button onclick="pywebview.api.install()">Установить</button>',
        ))
        return
    window.load_html(page("Запускаю SQUAD VPN…", "Это займёт несколько секунд"))
    start_agent(root)
    if wait_healthy(45):
        window.load_url(APP_URL)
    else:
        show_error(window, root, "SQUAD VPN не запустился",
                   "Фоновая программа не ответила за 45 секунд. Журнал подскажет причину.")


def main() -> int:
    root = project_root()
    try:
        import webview
    except ImportError:
        # No embedded browser available: fall back to the default browser.
        if not healthy() and (root / ".venv" / "Scripts" / "pythonw.exe").exists():
            start_agent(root)
            wait_healthy(45)
        webbrowser.open(APP_URL)
        return 0
    api = Api(root)
    window = webview.create_window(
        TITLE,
        html=page("SQUAD VPN", "Загрузка…"),
        js_api=api,
        width=1120,
        height=780,
        min_size=(400, 560),
    )
    api.window = window
    webview.start(boot, (window, root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
