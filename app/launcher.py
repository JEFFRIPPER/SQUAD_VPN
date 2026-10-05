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
:root {{ color-scheme:dark; --p:#d00018; --op:#fff; --s:#000000; --os:#F6EAEA; --v:#C7A5A5; --c:#190003;
  --emph:cubic-bezier(.05,.7,.1,1);
  --spring:linear(0, .051, .18, .352, .537, .714, .867, .99, 1.077, 1.132, 1.159, 1.162, 1.148, 1.124, 1.095,
    1.065, 1.037, 1.014, .996, .984, .976, .974, .974, .977, .981, .986, .991, .995, .999, 1.001, 1.003, 1); }}
html,body {{ height:100%; margin:0; }}
body {{ background:var(--s); color:var(--os); font:14px/20px "Segoe UI",Roboto,system-ui,sans-serif;
  display:grid; place-items:center; text-align:center; padding:24px; box-sizing:border-box; overflow:hidden; }}
body::before {{ content:""; position:fixed; inset:-30%; pointer-events:none;
  background:radial-gradient(closest-side, rgba(208,0,24,.22), transparent 70%);
  animation:glow 6s ease-in-out infinite alternate; }}
@keyframes glow {{ from {{ transform:translate(-8%,-6%) scale(.9); }} to {{ transform:translate(8%,6%) scale(1.1); }} }}
.wrap {{ position:relative; }}
.logo {{ width:96px; height:96px; border-radius:28px; background:var(--c); display:grid; place-items:center; margin:0 auto 24px;
  box-shadow:0 0 0 1px #4e0009, 0 0 48px rgba(208,0,24,.35); animation:pop .7s var(--spring) both; }}
.logo svg {{ animation:pop .7s .08s var(--spring) both; }}
@keyframes pop {{ from {{ transform:scale(.4); opacity:0; }} }}
h1 {{ font-size:28px; line-height:36px; font-weight:400; margin:0 0 8px; animation:rise .5s .1s var(--emph) both; }}
p {{ color:var(--v); max-width:440px; margin:0 auto 24px; animation:rise .5s .16s var(--emph) both; }}
.wrap > :nth-child(n+4) {{ animation:rise .5s .22s var(--emph) both; }}
@keyframes rise {{ from {{ opacity:0; transform:translateY(16px); }} }}
.spinner {{ width:48px; height:48px; margin:0 auto; animation:rot 1.6s linear infinite; }}
.spinner circle {{ fill:none; stroke:var(--p); stroke-width:4; stroke-linecap:round; stroke-dasharray:8 200;
  animation:arc 1.4s var(--emph) infinite; transform-origin:center; }}
@keyframes rot {{ to {{ transform:rotate(360deg); }} }}
@keyframes arc {{ 0% {{ stroke-dasharray:8 200; stroke-dashoffset:0; }}
  50% {{ stroke-dasharray:90 200; stroke-dashoffset:-30; }} 100% {{ stroke-dasharray:8 200; stroke-dashoffset:-125; }} }}
button {{ height:40px; padding:0 24px; border-radius:20px; border:0; background:var(--p); color:var(--op);
  font:500 14px "Segoe UI",Roboto,sans-serif; cursor:pointer; margin:4px;
  transition:transform .4s var(--spring), border-radius .3s var(--emph), box-shadow .2s; }}
button:hover {{ box-shadow:0 0 24px rgba(208,0,24,.45); }}
button:active {{ transform:scale(.94); border-radius:12px; transition-duration:.1s; }}
button.alt {{ background:transparent; color:var(--p); border:1px solid var(--v); }}
@media (prefers-reduced-motion: reduce) {{ *, *::before {{ animation-duration:.01ms !important; animation-iteration-count:1 !important; }} }}
</style></head><body><div class="wrap">
<div class="logo"><svg width="48" height="48" viewBox="0 0 24 24"><path fill="var(--p)"
 d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5zm-1.5 14.5-4-4 1.4-1.4 2.6 2.6 5.6-5.6 1.4 1.4z"/></svg></div>
<h1>{title}</h1><p>{text}</p>{body}</div></body></html>"""

SPINNER = '<svg class="spinner" viewBox="0 0 48 48"><circle cx="24" cy="24" r="20"/></svg>'

# Our own title bar: the window has no system frame. It is injected into every
# page the window shows (splash pages and the panel of any version), so even
# an older panel served by the agent can be moved, minimized and closed.
CHROME_JS = r"""
(() => {
  if (document.getElementById("sq-chrome")) return;
  const H = 40;
  const css = document.createElement("style");
  css.id = "sq-chrome-style";
  css.textContent = `
    html.sq-frameless body { padding-top: ${H}px !important; }
    #sq-chrome { position: fixed; top: 0; left: 0; right: 0; height: ${H}px; z-index: 2147483000;
      display: flex; align-items: center; background: rgba(0,0,0,.82); backdrop-filter: blur(16px);
      font: 500 12px/16px "Segoe UI", Roboto, system-ui, sans-serif; letter-spacing: .5px; color: #C7A5A5;
      user-select: none; animation: sq-in .45s cubic-bezier(.05,.7,.1,1) both; }
    #sq-chrome::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 1px;
      background: linear-gradient(90deg, transparent, #4e0009 20%, #4e0009 80%, transparent); }
    @keyframes sq-in { from { opacity: 0; transform: translateY(-100%); } }
    #sq-chrome .sq-drag { flex: 1; align-self: stretch; display: flex; align-items: center; gap: 10px; padding-left: 14px; }
    #sq-chrome .sq-logo { width: 22px; height: 22px; border-radius: 7px; background: #190003; display: grid; place-items: center;
      box-shadow: 0 0 0 1px #4e0009; transition: transform .5s linear(0, .18, .537, .867, 1.077, 1.159, 1.148, 1.095, 1.037, .996, .976, .977, .991, 1); }
    #sq-chrome:hover .sq-logo { transform: rotate(-8deg) scale(1.08); }
    #sq-chrome .sq-logo svg { width: 14px; height: 14px; fill: #d00018; }
    #sq-chrome .sq-btns { display: flex; gap: 2px; padding-right: 6px; }
    #sq-chrome button { width: 40px; height: 30px; border: 0; border-radius: 15px; background: transparent; color: #F6EAEA;
      display: grid; place-items: center; cursor: pointer; position: relative; overflow: hidden;
      transition: background .2s, border-radius .35s linear(0, .18, .537, .867, 1.077, 1.159, 1.148, 1.095, 1.037, .996, .976, .977, .991, 1),
        transform .35s linear(0, .18, .537, .867, 1.077, 1.159, 1.148, 1.095, 1.037, .996, .976, .977, .991, 1); }
    #sq-chrome button svg { width: 16px; height: 16px; fill: currentColor; pointer-events: none; }
    #sq-chrome button:hover { background: rgba(246,234,234,.08); border-radius: 10px; }
    #sq-chrome button:active { transform: scale(.88); }
    #sq-chrome button.sq-close:hover { background: #d00018; color: #fff; box-shadow: 0 0 18px rgba(208,0,24,.55); }
    .sq-edge { position: fixed; z-index: 2147483001; }
    .sq-edge[data-e="n"] { top: 0; left: 8px; right: 8px; height: 4px; cursor: ns-resize; }
    .sq-edge[data-e="s"] { bottom: 0; left: 8px; right: 8px; height: 5px; cursor: ns-resize; }
    .sq-edge[data-e="w"] { left: 0; top: 8px; bottom: 8px; width: 5px; cursor: ew-resize; }
    .sq-edge[data-e="e"] { right: 0; top: 8px; bottom: 8px; width: 5px; cursor: ew-resize; }
    .sq-edge[data-e="nw"] { left: 0; top: 0; width: 8px; height: 8px; cursor: nwse-resize; }
    .sq-edge[data-e="ne"] { right: 0; top: 0; width: 8px; height: 8px; cursor: nesw-resize; }
    .sq-edge[data-e="sw"] { left: 0; bottom: 0; width: 10px; height: 10px; cursor: nesw-resize; }
    .sq-edge[data-e="se"] { right: 0; bottom: 0; width: 10px; height: 10px; cursor: nwse-resize; }
    html.sq-max .sq-edge { display: none; }
    @media (prefers-reduced-motion: reduce) { #sq-chrome { animation: none; } }
  `;
  document.head.appendChild(css);
  document.documentElement.classList.add("sq-frameless");

  const icons = {
    min: '<svg viewBox="0 0 24 24"><path d="M5 11h14v2H5z"/></svg>',
    max: '<svg viewBox="0 0 24 24"><path d="M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2m0 2v12h12V6z"/></svg>',
    restore: '<svg viewBox="0 0 24 24"><path d="M8 3h11a2 2 0 0 1 2 2v11h-2V5H8zM5 7h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2m0 2v10h10V9z"/></svg>',
    close: '<svg viewBox="0 0 24 24"><path d="M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z"/></svg>',
  };
  const bar = document.createElement("div");
  bar.id = "sq-chrome";
  bar.innerHTML = `
    <div class="sq-drag pywebview-drag-region">
      <span class="sq-logo"><svg viewBox="0 0 24 24"><path d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5z"/></svg></span>
      <span>SQUAD VPN</span>
    </div>
    <div class="sq-btns">
      <button data-a="min" title="Свернуть">${icons.min}</button>
      <button data-a="max" title="Развернуть">${icons.max}</button>
      <button data-a="close" class="sq-close" title="Закрыть">${icons.close}</button>
    </div>`;
  document.body.appendChild(bar);

  const api = () => (window.pywebview && window.pywebview.api) || {};
  const call = (name, ...args) => { const f = api()[name]; return f ? f(...args) : Promise.resolve(); };

  // Maximize to the work area of the current screen (a frameless WinForms
  // window maximized by Windows would cover the taskbar).
  const S = window.__sqChrome = window.__sqChrome || { max: false, saved: null };
  const maxBtn = bar.querySelector('[data-a="max"]');
  function paintMax() {
    document.documentElement.classList.toggle("sq-max", S.max);
    maxBtn.innerHTML = S.max ? icons.restore : icons.max;
    maxBtn.title = S.max ? "Восстановить" : "Развернуть";
  }
  async function toggleMax() {
    if (!S.max) {
      S.saved = [window.screenX, window.screenY, window.innerWidth, window.innerHeight];
      await call("window_place", screen.availLeft || 0, screen.availTop || 0, screen.availWidth, screen.availHeight);
      S.max = true;
    } else {
      const [x, y, w, h] = S.saved || [window.screenX + 40, window.screenY + 40, 1120, 780];
      await call("window_place", x, y, w, h);
      S.max = false;
    }
    paintMax();
  }
  paintMax();
  bar.querySelector('[data-a="min"]').addEventListener("click", () => call("window_minimize"));
  maxBtn.addEventListener("click", toggleMax);
  bar.querySelector('[data-a="close"]').addEventListener("click", () => call("window_close"));
  bar.querySelector(".sq-drag").addEventListener("dblclick", toggleMax);

  // Resize by the edges: the frameless window has no native border.
  const MIN_W = 400, MIN_H = 560;
  for (const edge of ["n", "s", "w", "e", "nw", "ne", "sw", "se"]) {
    const el = document.createElement("div");
    el.className = "sq-edge";
    el.dataset.e = edge;
    document.body.appendChild(el);
    el.addEventListener("pointerdown", (down) => {
      if (S.max) return;
      down.preventDefault();
      el.setPointerCapture(down.pointerId);
      const start = { x: down.screenX, y: down.screenY, w: window.innerWidth, h: window.innerHeight };
      let pending = null, busy = false;
      const flush = async () => {
        if (busy || !pending) return;
        busy = true;
        const next = pending; pending = null;
        try { await call("window_resize", next.w, next.h, edge); } catch { /* ignore */ }
        busy = false;
        flush();
      };
      const move = (ev) => {
        const dx = ev.screenX - start.x, dy = ev.screenY - start.y;
        let w = start.w, h = start.h;
        if (edge.includes("e")) w += dx;
        if (edge.includes("w")) w -= dx;
        if (edge.includes("s")) h += dy;
        if (edge.includes("n")) h -= dy;
        pending = { w: Math.max(MIN_W, Math.round(w)), h: Math.max(MIN_H, Math.round(h)) };
        requestAnimationFrame(flush);
      };
      const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
    });
  }
})();
"""


def page(title: str, text: str, body: str = SPINNER) -> str:
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

    # Window controls for our own title bar (CHROME_JS).
    def window_minimize(self) -> None:
        self._window.minimize()

    def window_close(self) -> None:
        self._window.destroy()

    def window_place(self, x: int, y: int, width: int, height: int) -> None:
        self._window.move(int(x), int(y))
        self._window.resize(int(width), int(height))

    def window_resize(self, width: int, height: int, edge: str = "se") -> None:
        """Resize from an edge, keeping the opposite side in place."""
        from webview.window import FixPoint

        fix = FixPoint.EAST if "w" in edge else FixPoint.WEST
        fix |= FixPoint.SOUTH if "n" in edge else FixPoint.NORTH
        self._window.resize(max(400, int(width)), max(560, int(height)), fix)

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


def add_chrome(window) -> None:
    try:
        window.evaluate_js(CHROME_JS)
    except Exception:  # a page that is already gone; the next load adds it
        pass


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
        frameless=True,
        easy_drag=False,
        background_color="#000000",
    )
    api._window = window
    window.events.loaded += lambda: add_chrome(window)
    webview.start(boot, (window, root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
