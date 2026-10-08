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


# install.cmd writes "STEP <n> <name>" lines to data/logs/install.log.
INSTALL_STEPS = {
    "1": "Шаг 1 из 6: Git для обновлений (ставится в фоне)",
    "2": "Шаг 2 из 6: ставлю Python, это самый долгий шаг, обычно 1–5 минут",
    "3": "Шаг 3 из 6: ставлю библиотеки",
    "4": "Шаг 4 из 6: останавливаю старую версию",
    "5": "Шаг 5 из 6: включаю автозапуск",
    "6": "Шаг 6 из 6: запускаю SQUAD VPN",
}
FAILED_STEPS = {"python": "Python", "venv": "Python", "deps": "библиотеки", "autostart": "автозапуск"}


def install_progress(root: Path) -> tuple[str, str]:
    """Current step of the running install.cmd and the failed step, if any."""
    try:
        lines = (root / "data" / "logs" / "install.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "", ""
    begins = [i for i, line in enumerate(lines) if line.rstrip().endswith("BEGIN")]
    step = failed = ""
    for line in lines[begins[-1] if begins else 0:]:
        words = line.split()
        if "STEP" in words and words.index("STEP") + 1 < len(words):
            step = INSTALL_STEPS.get(words[words.index("STEP") + 1], step)
        elif "FAIL" in words and words.index("FAIL") + 1 < len(words):
            failed = FAILED_STEPS.get(words[words.index("FAIL") + 1], words[words.index("FAIL") + 1])
    return step, failed


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
.logo {{ width:96px; height:96px; border-radius:28px; background:var(--c); overflow:hidden; margin:0 auto 24px;
  box-shadow:0 0 0 1px #4e0009, 0 0 48px rgba(208,0,24,.35); animation:pop .7s var(--spring) both; }}
.logo img {{ width:100%; height:100%; display:block; animation:pop .7s .08s var(--spring) both; }}
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
<div class="logo"><img src="{logo}" alt=""></div>
<h1>{title}</h1><p>{text}</p>{body}</div></body></html>"""

# The SQUAD logo (assets/logo.jpg, 160 px) for the splash and the title bar.
LOGO = "data:image/jpeg;base64,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"

SPINNER = '<svg class="spinner" viewBox="0 0 48 48"><circle cx="24" cy="24" r="20"/></svg>'

# Our own title bar: the window has no system frame. It is injected into every
# page the window shows (splash pages and the panel of any version), so even
# an older panel served by the agent can be moved, minimized and closed.
CHROME_JS = r"""
(() => {
  if (document.getElementById("sq-chrome")) return;
  const H = 40;
  const LOGO = "__LOGO__";
  const css = document.createElement("style");
  css.id = "sq-chrome-style";
  css.textContent = `
    html.sq-frameless body { padding-top: ${H}px !important; }
    #sq-chrome { position: fixed; top: 0; left: 0; right: 0; height: ${H}px; z-index: 2147483000;
      display: flex; align-items: center; background: rgba(12,2,4,.62); backdrop-filter: blur(24px) saturate(1.25);
      font: 500 12px/16px "Segoe UI", Roboto, system-ui, sans-serif; letter-spacing: .5px; color: #C7A5A5;
      user-select: none; animation: sq-in .45s cubic-bezier(.05,.7,.1,1) both; }
    #sq-chrome::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 1px;
      background: linear-gradient(90deg, transparent, #4e0009 20%, #4e0009 80%, transparent); }
    @keyframes sq-in { from { opacity: 0; transform: translateY(-100%); } }
    #sq-chrome .sq-drag { flex: 1; align-self: stretch; display: flex; align-items: center; gap: 10px; padding-left: 14px; }
    #sq-chrome .sq-logo { width: 22px; height: 22px; border-radius: 7px; background: #190003; display: grid; place-items: center;
      box-shadow: 0 0 0 1px #4e0009; transition: transform .5s linear(0, .18, .537, .867, 1.077, 1.159, 1.148, 1.095, 1.037, .996, .976, .977, .991, 1); }
    #sq-chrome:hover .sq-logo { transform: rotate(-8deg) scale(1.08); }
    #sq-chrome .sq-logo { overflow: hidden; }
    #sq-chrome .sq-logo img { width: 100%; height: 100%; display: block; }
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
      <span class="sq-logo"><img src="${LOGO}" alt=""></span>
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

    return PAGE.format(title=escape(title), text=escape(text), body=body, logo=LOGO)


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
        self._window.load_html(page("Устанавливаю…", "Открылось окно установки, оно закроется само."))
        threading.Thread(target=self._after_install, daemon=True).start()

    def _after_install(self) -> None:
        started = time.monotonic()
        shown = None
        while time.monotonic() - started < 900:
            if healthy():
                self._window.load_url(APP_URL)
                return
            step, failed = install_progress(self._root)
            if failed:
                log(self._root, f"install failed at {failed}")
                show_error(self._window, self._root, "Установка не завершилась",
                           f"Ошибка на шаге «{failed}». Посмотри окно установки и пришли текст ошибки.")
                return
            minutes = int(time.monotonic() - started) // 60
            text = f"{step}. Прошло {minutes} мин." if step else "Готовлю установку…"
            if text != shown:
                self._window.load_html(page("Устанавливаю…", text))
                shown = text
            time.sleep(2)
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
        window.evaluate_js(CHROME_JS.replace("__LOGO__", LOGO))
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
