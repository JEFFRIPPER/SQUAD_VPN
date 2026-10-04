"""SQUAD VPN.exe — desktop window for the SQUAD VPN control panel.

The exe is a thin shell: it lives in the project folder, makes sure the
background agent runs (or offers to install it) and shows the panel served
by the agent at http://127.0.0.1:8080/app. The panel itself comes from the
project code, so it updates together with the project without a new exe.

Only the standard library and pywebview are used here on purpose.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path


PORT = 8080
BASE = f"http://127.0.0.1:{PORT}"
APP_URL = f"{BASE}/app"
TITLE = "SQUAD VPN"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
NEW_CONSOLE = 0x00000010  # CREATE_NEW_CONSOLE
REPO = "JEFFRIPPER/SQUAD_VPN"
SOURCE_ZIP = f"https://codeload.github.com/{REPO}/zip/refs/heads/main"
APP_NAME = "SQUAD VPN.exe"

try:  # written by the release build (build-app.yml)
    from build_info import VERSION
except ImportError:
    VERSION = "dev"


def default_install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "SQUAD VPN"


def installed_copy() -> Path | None:
    """A previous installation in the default place, if any."""
    target = default_install_dir()
    return target if (target / "pyproject.toml").exists() else None


def download_source(target: Path, progress=lambda text: None) -> None:
    """Fetch the project from GitHub and unpack it into ``target``."""
    progress("Скачиваю SQUAD VPN с GitHub…")
    with urllib.request.urlopen(SOURCE_ZIP, timeout=120) as response:
        payload = response.read()
    progress("Распаковываю…")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        prefix = archive.namelist()[0].split("/")[0] + "/"
        target.mkdir(parents=True, exist_ok=True)
        for member in archive.infolist():
            relative = member.filename[len(prefix):]
            if not relative or member.is_dir():
                continue
            destination = (target / relative).resolve()
            if target.resolve() not in destination.parents:
                continue  # never write outside the target folder
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(destination, "wb") as out:
                shutil.copyfileobj(source, out)


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
:root {{ color-scheme:dark; --p:#d00018; --op:#fff; --s:#000000; --os:#F6EAEA; --v:#C7A5A5; --c:#190003; }}
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
    """Title and text are escaped (they may hold paths and error messages)."""
    from html import escape

    return PAGE.format(title=escape(title), text=escape(text), body=body)


class Api:
    """Functions callable from the splash pages (window.pywebview.api.*).

    pywebview exposes every public attribute of this object to JavaScript and
    walks into it recursively. Holding the window in a public attribute made
    it reflect over the whole native window on the UI thread and freeze
    ("Не отвечает"), so all state is private (underscore).
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._window = None

    def install(self) -> None:
        installer = self._root / "install.cmd"
        subprocess.Popen(
            ["cmd", "/c", str(installer)], cwd=self._root, creationflags=NEW_CONSOLE,
            env={**os.environ, "SQUAD_FROM_APP": "1"},
        )
        self._window.load_html(page(
            "Устанавливаю…",
            "Открылось окно установки: дождись слова Done. Это окно само переключится на панель.",
        ))
        threading.Thread(target=self._after_install, daemon=True).start()

    def _after_install(self) -> None:
        if wait_healthy(900):
            self._window.load_url(APP_URL)
        else:
            show_error(self._window, self._root, "Установка не завершилась",
                       "Посмотри окно установки: если там ошибка, пришли её текст.")

    def setup_fresh(self) -> None:
        """Install SQUAD VPN from scratch into %LOCALAPPDATA%\\SQUAD VPN."""
        threading.Thread(target=self._setup_fresh, daemon=True).start()

    def _setup_fresh(self) -> None:
        target = default_install_dir()
        try:
            if not (target / "pyproject.toml").exists():
                download_source(target, lambda text: self._window.load_html(page(text, str(target))))
            exe = Path(sys.executable)
            if getattr(sys, "frozen", False) and exe.resolve() != (target / APP_NAME).resolve():
                shutil.copy2(exe, target / APP_NAME)
            log(target, f"fresh setup into {target}")
            self._root = target
            self.install()
        except Exception as exc:
            log(target, f"fresh setup failed: {exc!r}")
            show_error(self._window, target, "Не удалось установить",
                       f"{type(exc).__name__}: {exc}. Проверь интернет и попробуй снова.")

    def open_installed(self) -> None:
        target = installed_copy()
        if target is None:
            return
        subprocess.Popen([str(target / APP_NAME)], cwd=target, close_fds=True)
        self._window.destroy()

    def version(self) -> str:
        """Build of this running exe, e.g. 1.2.0-abc1234 (the panel compares it)."""
        return VERSION

    def relaunch(self) -> bool:
        """Start the exe that the agent downloaded over the air and close this one."""
        target = self._root / APP_NAME
        if not target.exists():
            return False
        log(self._root, f"relaunch into the updated app ({VERSION} -> new)")
        subprocess.Popen([str(target)], cwd=self._root, close_fds=True)
        self._window.destroy()
        return True

    def retry(self) -> None:
        threading.Thread(target=boot, args=(self._window, self._root), daemon=True).start()

    def open_logs(self) -> None:
        folder = self._root / "data" / "logs"
        os.startfile(folder if folder.exists() else self._root)  # type: ignore[attr-defined]


def show_error(window, root: Path, title: str, text: str) -> None:
    window.load_html(page(
        title,
        text,
        '<button onclick="pywebview.api.retry()">Повторить</button>'
        '<button class="alt" onclick="pywebview.api.open_logs()">Открыть журнал</button>',
    ))


def log(root: Path, message: str) -> None:
    """The exe has no console: write what happens to data/logs/app.log."""
    try:
        folder = root / "data" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "app.log", "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def boot(window, root: Path) -> None:
    try:
        _boot(window, root)
    except Exception as exc:  # never leave the user on an endless spinner
        log(root, f"boot failed: {exc!r}")
        show_error(window, root, "Что-то пошло не так", f"{type(exc).__name__}: {exc}")


def _boot(window, root: Path) -> None:
    log(root, f"start {VERSION}, root={root}")
    if not (root / "pyproject.toml").exists():
        existing = installed_copy()
        if existing is not None and (existing / APP_NAME).exists():
            window.load_html(page(
                "SQUAD VPN уже установлен",
                f"Он в папке {existing}. Открыть его?",
                '<button onclick="pywebview.api.open_installed()">Открыть SQUAD VPN</button>',
            ))
            return
        window.load_html(page(
            "Установить SQUAD VPN?",
            f"Программа скачается с GitHub в {default_install_dir()}, сама поставит Python "
            "и всё нужное, включит автозапуск и создаст ярлык. Это займёт несколько минут.",
            '<button onclick="pywebview.api.setup_fresh()">Установить</button>',
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
    log(root, "agent started, waiting for the server")
    if wait_healthy(45):
        log(root, "server is up")
        window.load_url(APP_URL)
    else:
        log(root, "server did not answer in 45 s")
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
    api._window = window
    webview.start(boot, (window, root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
