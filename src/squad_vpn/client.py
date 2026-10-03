"""SQUAD VPN client: routes this computer's traffic through the best nodes.

The Mihomo core (already used for validation) runs with a config built from
one of the user's profiles and listens on a local mixed (HTTP+SOCKS) port;
the Windows system proxy points at it. A monitor watches the current node:
when it stops answering or its ping degrades, it makes the core re-test and
switch to the best node, and it refreshes the node list as the database
learns. Traffic and switches are recorded as sessions.

Safety: the previous proxy settings and the core's PID are kept in
``data/client/state.json``; if anything dies, the agent or the next start
restores the proxy, so the user never stays without internet.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx

from . import sysproxy
from .exporter import mihomo_config, mihomo_proxies
from .mihomo import dump_yaml
from .smart import DEFAULT_PROFILES_PATH, GROUP_PROFILE, load_profiles, select_profile
from .store import NodeStore
from .validator import DEFAULT_BINARY


CLIENT_DIR = Path("data/client")
MIXED_PORT = 7890
CONTROLLER_PORT = 9097
TEST_URL = "https://www.gstatic.com/generate_204"
TRAFFIC_EVERY = 2.0
HEALTH_EVERY = 15.0
REFRESH_EVERY = 30 * 60.0
# When nothing better exists, do not reload (it drops connections) or repeat
# the same event more often than this.
DEGRADED_COOLDOWN = 5 * 60.0
DEGRADED_MIN_MS = 1500.0
MAX_NODES = 120
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_client_config(
    nodes: list, *, secret: str, mixed_port: int, controller_port: int
) -> tuple[dict[str, object], dict[str, str]]:
    """Mihomo config for everyday use plus a map proxy name -> fingerprint."""
    config = mihomo_config(nodes, "SQUAD")
    names = {proxy["name"]: node.fingerprint for node, proxy in mihomo_proxies(nodes, "SQUAD")}
    for group in config["proxy-groups"]:  # type: ignore[union-attr]
        if group["type"] in ("url-test", "fallback"):
            # Not lazy: keep measuring even when idle, so a switch is instant.
            group.update({"lazy": False, "interval": 120, "url": TEST_URL})
            if group["type"] == "url-test":
                group["tolerance"] = 80
    config.update(
        {
            "mixed-port": mixed_port,
            "allow-lan": False,
            "bind-address": "127.0.0.1",
            "external-controller": f"127.0.0.1:{controller_port}",
            "secret": secret,
            "log-level": "warning",
            "profile": {"store-selected": False},
        }
    )
    return config, names


class ClientState:
    """Small JSON file that survives crashes: what to undo, what to resume."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, object]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, data: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _core_alive(controller_port: int, secret: str, timeout: float = 2.0) -> bool:
    """True only for *our* core: it must answer with our secret."""
    try:
        response = httpx.get(
            f"http://127.0.0.1:{controller_port}/version",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=timeout,
            trust_env=False,
        )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def cleanup_orphan(
    root: Path,
    *,
    backend: sysproxy.ProxyBackend | None = None,
    clear_resume: bool = False,
    controller_port: int = CONTROLLER_PORT,
    mixed_port: int = MIXED_PORT,
) -> dict[str, object]:
    """Undo a connection left behind by a crash or a stop.

    Restores the system proxy if it still points at us and stops our core
    (identified by its secret, so an unrelated process with a reused PID is
    never killed). ``clear_resume`` also forgets that the user was
    connected (explicit stop); otherwise the next start reconnects.
    """
    backend = backend or sysproxy.default_backend()
    state_file = ClientState(root / CLIENT_DIR / "state.json")
    state = state_file.load()
    result = {"proxy_restored": False, "core_stopped": False}
    if not state:
        return result
    if state.get("proxy_set") and backend.supported:
        previous = state.get("previous_proxy")
        result["proxy_restored"] = sysproxy.restore(
            backend,
            sysproxy.ProxyState.parse(previous),
            mixed_port,
        )
    pid = state.get("pid")
    secret = str(state.get("secret") or "")
    if pid and secret and _core_alive(controller_port, secret):
        try:
            os.kill(int(pid), signal.SIGTERM)
            result["core_stopped"] = True
        except OSError:
            pass
    state.update({"proxy_set": False, "pid": None})
    if clear_resume:
        state["connected"] = False
    state_file.save(state)
    return result


class VpnClient:
    def __init__(
        self,
        database: Path,
        *,
        root: Path = Path("."),
        profiles_path: Path | None = DEFAULT_PROFILES_PATH,
        binary: Path = DEFAULT_BINARY,
        backend: sysproxy.ProxyBackend | None = None,
        mixed_port: int = MIXED_PORT,
        controller_port: int = CONTROLLER_PORT,
        spawn: Callable[[list[str], Path], object] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self.database = Path(database)
        self.root = Path(root)
        self.profiles_path = profiles_path
        self.binary = Path(binary)
        self.backend = backend or sysproxy.default_backend()
        self.mixed_port = mixed_port
        self.controller_port = controller_port
        self._spawn = spawn or self._spawn_core
        self._transport = transport
        self._log = log
        self.dir = self.root / CLIENT_DIR
        self.state = ClientState(self.dir / "state.json")
        self._process = None
        self._monitor: asyncio.Task | None = None
        self._restart_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._secret = ""
        self._names: dict[str, str] = {}
        self._session: int | None = None
        self.status: dict[str, object] = {"state": "disconnected"}
        self._reset_counters()

    # --- helpers ---------------------------------------------------------

    def _reset_counters(self) -> None:
        self._base_up = self._base_down = 0
        self._last_totals: tuple[float, int, int] | None = None
        self._session_up = self._session_down = 0
        self._switches = 0
        self._fails = 0
        self._delays: list[float] = []
        self._degraded_since: float | None = None

    def _api(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{self.controller_port}",
            headers={"Authorization": f"Bearer {self._secret}"},
            timeout=6.0,
            trust_env=False,
            transport=self._transport,
        )

    def _spawn_core(self, command: list[str], log_path: Path) -> object:
        with open(log_path, "ab") as output:
            return subprocess.Popen(
                command, stdout=output, stderr=subprocess.STDOUT, creationflags=NO_WINDOW
            )

    def _event(self, kind: str, node: str | None = None, detail: str | None = None) -> None:
        self._log(f"[клиент] {kind}: {node or ''} {detail or ''}".rstrip())
        store = NodeStore(self.database, init_schema=False)
        try:
            store.add_client_event(kind, node, detail)
        finally:
            store.close()

    def _select(self, profile_name: str) -> tuple[str, list]:
        profiles = {p.name: p for p in load_profiles(self.profiles_path)}
        store = NodeStore(self.database, init_schema=False)
        try:
            chosen = profiles.get(profile_name)
            records = select_profile(store, replace(chosen, limit=min(chosen.limit, MAX_NODES))) if chosen else []
            if not records:
                # Profile empty right now (e.g. no fresh RU report): use all alive nodes.
                records = select_profile(store, replace(GROUP_PROFILE, name="fallback", limit=MAX_NODES))
                if chosen:
                    profile_name = f"{profile_name} → все живые"
        finally:
            store.close()
        self._records = {item.node.fingerprint: item for item in records}
        return profile_name, [item.node for item in records]

    def _write_config(self, nodes: list) -> Path:
        config, self._names = build_client_config(
            nodes,
            secret=self._secret,
            mixed_port=self.mixed_port,
            controller_port=self.controller_port,
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / "config.yaml"
        path.write_text(dump_yaml(config), encoding="utf-8")
        return path

    async def _wait_ready(self, seconds: float = 15.0) -> None:
        deadline = time.monotonic() + seconds
        async with self._api() as api:
            while time.monotonic() < deadline:
                if self._process is not None and getattr(self._process, "poll", lambda: None)() is not None:
                    raise RuntimeError("Ядро Mihomo завершилось при запуске — см. data/client/mihomo.log")
                try:
                    if (await api.get("/version")).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.3)
        raise TimeoutError("Ядро Mihomo не ответило за 15 секунд")

    # --- public API ------------------------------------------------------

    async def connect(self, profile: str) -> dict[str, object]:
        async with self._lock:
            if self.status["state"] in ("connected", "connecting"):
                return self.snapshot()
            cleanup_orphan(self.root, backend=self.backend, controller_port=self.controller_port,
                           mixed_port=self.mixed_port)
            self.status = {"state": "connecting", "profile": profile, "since": _now()}
            try:
                if not self.binary.exists():
                    raise FileNotFoundError("Mihomo ещё не скачан — дождись первого обновления узлов")
                label, nodes = await asyncio.to_thread(self._select, profile)
                if not nodes:
                    raise RuntimeError("Нет живых узлов: дождись проверки или нажми «Обновить узлы»")
                self._secret = secrets.token_hex(16)
                config_path = self._write_config(nodes)
                self._process = self._spawn(
                    [str(self.binary.resolve()), "-f", str(config_path.resolve()), "-d", str(self.dir.resolve())],
                    self.dir / "mihomo.log",
                )
                self.state.save(
                    {"connected": True, "profile": profile, "pid": getattr(self._process, "pid", None),
                     "secret": self._secret, "proxy_set": False, "started_at": _now()}
                )
                await self._wait_ready()
                proxy_set = False
                previous = None
                if self.backend.supported:
                    previous = sysproxy.enable(self.backend, self.mixed_port)
                    proxy_set = True
                state = self.state.load()
                state.update({"proxy_set": proxy_set,
                              "previous_proxy": previous.as_dict() if previous else None})
                self.state.save(state)
            except Exception as exc:
                self.status = {"state": "error", "profile": profile, "error": str(exc)}
                await asyncio.to_thread(self._stop_core)
                cleanup_orphan(self.root, backend=self.backend, clear_resume=True,
                               controller_port=self.controller_port, mixed_port=self.mixed_port)
                self._event("error", None, str(exc))
                return self.snapshot()
            self._reset_counters()
            store = NodeStore(self.database, init_schema=False)
            try:
                store.close_open_sessions("restart")
                self._session = store.start_session(label)
            finally:
                store.close()
            self.status = {
                "state": "connected", "profile": profile, "profile_label": label,
                "since": _now(), "nodes": len(self._names), "proxy_set": proxy_set,
                "port": self.mixed_port, "node": None, "delay_ms": None,
                "speed_up": 0, "speed_down": 0,
            }
            self._event("connect", None, f"профиль {label}, узлов {len(self._names)}")
            self._monitor = asyncio.create_task(self._run_monitor())
            return self.snapshot()

    async def disconnect(self, reason: str = "user", *, keep_resume: bool = False) -> dict[str, object]:
        async with self._lock:
            if self._monitor is not None:
                self._monitor.cancel()
                try:
                    await self._monitor
                except (asyncio.CancelledError, Exception):
                    pass
                self._monitor = None
            if self.status.get("state") not in ("connected", "connecting", "error"):
                return self.snapshot()
            restored = False
            state = self.state.load()
            if state.get("proxy_set") and self.backend.supported:
                previous = state.get("previous_proxy")
                restored = sysproxy.restore(
                    self.backend,
                    sysproxy.ProxyState.parse(previous),
                    self.mixed_port,
                )
            await asyncio.to_thread(self._stop_core)
            state.update({"proxy_set": False, "pid": None,
                          "connected": bool(keep_resume and state.get("connected"))})
            self.state.save(state)
            self._close_session(reason)
            if self.status.get("state") == "connected":
                self._event("disconnect", self.status.get("node"), reason)  # type: ignore[arg-type]
            self.status = {"state": "disconnected", "proxy_restored": restored}
            return self.snapshot()

    async def choose(self, node: str | None) -> dict[str, object]:
        """Pin a node by name, or ``None`` to go back to automatic choice."""
        if self.status.get("state") != "connected":
            raise RuntimeError("Не подключено")
        target = node or "AUTO"
        if node is not None and node not in self._names:
            raise ValueError("Такого узла нет в текущем подключении")
        async with self._api() as api:
            response = await api.put("/proxies/SQUAD", json={"name": target})
            response.raise_for_status()
            # A manual choice is not an automatic switch: sync before health.
            self.status["node"] = await self._current(api)
        self._delays.clear()
        self.status["pinned"] = node
        self._event("pin" if node else "auto", node)
        await self._health(force=True)
        return self.snapshot()

    async def failover(self) -> dict[str, object]:
        if self.status.get("state") != "connected":
            raise RuntimeError("Не подключено")
        await self._switch("вручную")
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        data = dict(self.status)
        fingerprint = self._names.get(str(data.get("node") or ""))
        record = getattr(self, "_records", {}).get(fingerprint) if fingerprint else None
        if record is not None:
            data["node_info"] = {
                "name": record.node.display_name(),
                "protocol": record.node.protocol,
                "country": record.country,
                "score": record.quality_score,
            }
        if self._session is not None and data.get("state") == "connected":
            data["session"] = {
                "up": self._session_up, "down": self._session_down, "switches": self._switches,
            }
        return data

    def node_names(self) -> list[dict[str, object]]:
        result = []
        for name, fingerprint in self._names.items():
            record = getattr(self, "_records", {}).get(fingerprint)
            result.append({
                "name": name,
                "label": record.node.display_name() if record else name,
                "country": record.country if record else None,
                "latency_ms": record.latency_ms if record else None,
            })
        return result

    # --- monitor ---------------------------------------------------------

    async def _run_monitor(self) -> None:
        last_health = 0.0
        last_refresh = time.monotonic()
        while True:
            try:
                await self._traffic()
                if time.monotonic() - last_health >= HEALTH_EVERY:
                    last_health = time.monotonic()
                    await self._health()
                if time.monotonic() - last_refresh >= REFRESH_EVERY:
                    last_refresh = time.monotonic()
                    await self._refresh()
                if self._process is not None and getattr(self._process, "poll", lambda: None)() is not None:
                    self._event("crash", self.status.get("node"), "ядро завершилось, перезапускаю")  # type: ignore[arg-type]
                    profile = str(self.status.get("profile"))
                    # Keep a reference: an unreferenced task may be garbage-collected.
                    self._restart_task = asyncio.create_task(self._restart(profile))
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep monitoring whatever happens
                self._log(f"[клиент] монитор: {exc}")
            await asyncio.sleep(TRAFFIC_EVERY)

    async def _restart(self, profile: str) -> None:
        await self.disconnect("crash", keep_resume=True)
        await self.connect(profile)

    async def _traffic(self) -> None:
        async with self._api() as api:
            data = (await api.get("/connections")).json()
        up, down = int(data.get("uploadTotal") or 0), int(data.get("downloadTotal") or 0)
        now = time.monotonic()
        if self._last_totals is not None:
            last_at, last_up, last_down = self._last_totals
            if up < last_up or down < last_down:  # core restarted: counters reset
                last_up, last_down = 0, 0
            elapsed = max(now - last_at, 0.001)
            self.status["speed_up"] = int((up - last_up) / elapsed)
            self.status["speed_down"] = int((down - last_down) / elapsed)
            self._session_up += up - last_up
            self._session_down += down - last_down
        self._last_totals = (now, up, down)
        if self._session is not None and int(now) % 30 < TRAFFIC_EVERY:
            self._save_session()

    async def _current(self, api: httpx.AsyncClient) -> str | None:
        squad = (await api.get("/proxies/SQUAD")).json()
        now = squad.get("now")
        if now in ("AUTO", "FAILOVER"):
            now = (await api.get(f"/proxies/{now}")).json().get("now")
        return now

    async def _delay(self, api: httpx.AsyncClient, name: str) -> float | None:
        try:
            response = await api.get(
                f"/proxies/{name}/delay", params={"url": TEST_URL, "timeout": 3000}
            )
            if response.status_code != 200:
                return None
            return float(response.json()["delay"])
        except (httpx.HTTPError, KeyError, ValueError):
            return None

    def _degraded(self, delay: float) -> bool:
        if len(self._delays) < 4:
            return delay > DEGRADED_MIN_MS * 2
        typical = sorted(self._delays)[len(self._delays) // 2]
        return delay > max(DEGRADED_MIN_MS, typical * 3)

    async def _health(self, *, force: bool = False) -> None:
        async with self._api() as api:
            node = await self._current(api)
            previous = self.status.get("node")
            if node != previous:
                self._delays.clear()
                if previous and node:
                    # The core's own url-test moved to a better node.
                    self._switches += 1
                    self._event("switch", node, f"с {previous}: автовыбор ядра")
            self.status["node"] = node
            if node is None:
                return
            delay = await self._delay(api, node)
        self.status["delay_ms"] = delay
        self.status["checked_at"] = _now()
        if delay is not None and not self._degraded(delay):
            self._fails = 0
            self._delays = (self._delays + [delay])[-10:]
            if self._degraded_since is not None:
                self._degraded_since = None
                self._event("recovered", node, f"ping {int(delay)} ms")
            return
        self._fails += 1
        if self.status.get("pinned"):
            now = time.monotonic()
            if self._fails >= 2 and (
                self._degraded_since is None or now - self._degraded_since >= DEGRADED_COOLDOWN
            ):
                self._degraded_since = now
                self._event("degraded", node, "закреплённый узел не отвечает")
            return
        if self._fails >= 2 or force:
            reason = "не отвечает" if delay is None else f"ping {int(delay)} ms"
            await self._switch(reason)

    async def _switch(self, reason: str) -> None:
        before = self.status.get("node")
        async with self._api() as api:
            # Re-test the whole group now; url-test then moves to the best node.
            await api.get("/group/AUTO/delay", params={"url": TEST_URL, "timeout": 3000},
                          timeout=20.0)
            after = await self._current(api)
            delay = await self._delay(api, after) if after else None
        self._fails = 0
        self._delays.clear()
        if after and after != before:
            self._switches += 1
            self.status.update({"node": after, "delay_ms": delay})
            self._event("switch", after, f"с {before}: {reason}")
        elif delay is None:
            now = time.monotonic()
            if self._degraded_since is not None and now - self._degraded_since < DEGRADED_COOLDOWN:
                return  # already reported and reloaded recently
            self._degraded_since = now
            self._event("degraded", before, f"{reason}; замены лучше нет — обновляю список")  # type: ignore[arg-type]
            await self._refresh(force=True)

    async def _refresh(self, *, force: bool = False) -> None:
        """Reload the node list from the database when it changed noticeably."""
        _, nodes = await asyncio.to_thread(self._select, str(self.status.get("profile")))
        if not nodes:
            return
        new = {node.fingerprint for node in nodes}
        old = set(self._names.values())
        changed = len(new ^ old) / max(len(old | new), 1)
        if changed == 0 or (not force and changed < 0.3):
            return
        config_path = self._write_config(nodes)
        async with self._api() as api:
            response = await api.put(
                "/configs", params={"force": "true"}, json={"path": str(config_path.resolve())},
                timeout=20.0,
            )
            response.raise_for_status()
        self.status["nodes"] = len(self._names)
        self._event("reload", None, f"узлов {len(self._names)}, изменилось {int(changed * 100)}%")

    def _save_session(self, *, ended: bool = False, reason: str | None = None) -> None:
        if self._session is None:
            return
        store = NodeStore(self.database, init_schema=False)
        try:
            store.update_session(
                self._session, bytes_up=self._session_up, bytes_down=self._session_down,
                switches=self._switches, ended=ended, reason=reason,
            )
        finally:
            store.close()

    def _close_session(self, reason: str) -> None:
        self._save_session(ended=True, reason=reason)
        self._session = None

    def _stop_core(self) -> None:
        process = self._process
        self._process = None
        if process is None or not hasattr(process, "terminate"):
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
