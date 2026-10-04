from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import AppConfig, load_config
from .keys import SCOPES, KeyStore, allows
from .ratelimit import RateLimiter, TtlCache

from . import __version__
from .cycle import CycleOptions, run_cycle
from .validator import DEFAULT_BINARY

if TYPE_CHECKING:
    from .client import VpnClient
from .branding import DEFAULT_BRANDING_PATH, load_branding
from .exporter import ranked_to_dict
from .smart import (
    DEFAULT_PROFILES_PATH,
    GROUP_PROFILE,
    load_profiles,
    render_subscription,
    select_profile,
)
from .store import SORT_COLUMNS, NodeStore


MAX_SUB_LIMIT = 2000
MAX_PAGE_LIMIT = 500


def _dashboard_html(name: str = "index.html") -> str:
    return (
        resources.files("squad_vpn")
        .joinpath(f"dashboard/{name}")
        .read_text(encoding="utf-8")
    )


LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
# Requests from this very computer: no key needed, no rate limit.
REAL_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def lan_address() -> str | None:
    """This computer's address in the local network (no packet is sent)."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))
            address = sock.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") else address


def _host_allowed(hostname: str) -> bool:
    """Only IP addresses and localhost may name this server.

    A web page can make a browser send requests to 127.0.0.1, and with DNS
    rebinding even read the answers (its own domain resolving to 127.0.0.1).
    Such requests carry the attacker's domain in Host; rejecting every
    domain name except localhost closes that hole.
    """
    import ipaddress

    hostname = hostname.strip("[]").lower()
    if hostname in {"localhost", "testserver"}:
        return True
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


LOG_FILES = {"agent": "agent.log", "server": "squad.log", "crash": "server.log", "app": "app.log"}


def _require_local(request: Request) -> None:
    """Control actions (restart, settings, autostart) only from this computer."""
    host = request.client.host if request.client else ""
    if host not in LOOPBACK:
        raise HTTPException(status_code=403, detail="Только с этого компьютера")


def _tail(path: Path, lines: int) -> list[str]:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 200_000))
            data = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return data.splitlines()[-lines:]


class CycleRunner:
    """Runs the full cycle in the background of the API process."""

    def __init__(self, options: CycleOptions, interval_minutes: int) -> None:
        self.options = options
        self.interval = max(1, int(interval_minutes)) * 60
        self.running = False
        self.last: dict[str, object] | None = None
        self.next_run_at: str | None = None
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()

    _logger = logging.getLogger("squad_vpn.cycle")
    on_finish = None  # set by create_app: invalidate caches, make backups

    @classmethod
    def _log(cls, message: str) -> None:
        cls._logger.info(message)

    async def run_once(self) -> None:
        async with self._lock:
            self.running = True
            try:
                report = await run_cycle(self.options, log=self._log)
                self.last = report.as_dict()
                if self.on_finish is not None:
                    await self.on_finish()
            finally:
                self.running = False

    async def loop(self) -> None:
        while True:
            await self.run_once()
            self.next_run_at = (
                datetime.now(UTC) + timedelta(seconds=self.interval)
            ).isoformat(timespec="seconds")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
            except TimeoutError:
                pass

    def trigger(self) -> bool:
        if self.running:
            return False
        self._wake.set()
        return True

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "running": self.running,
            "interval_minutes": self.interval // 60,
            "next_run_at": None if self.running else self.next_run_at,
            "last": self.last,
        }


def create_app(
    database: str | Path,
    *,
    token: str | None = None,
    cycle: CycleOptions | None = None,
    interval_minutes: int = 60,
    profiles_path: str | Path | None = DEFAULT_PROFILES_PATH,
    client: "VpnClient | None" = None,
    client_root: Path | None = None,
    config: AppConfig | None = None,
    branding_path: str | Path | None = DEFAULT_BRANDING_PATH,
) -> FastAPI:
    """Build the HTTP API.

    When ``token`` is set, ``/sub`` and ``/api/*`` require it either as
    ``?token=`` (subscription clients cannot send headers) or as
    ``Authorization: Bearer``. ``/``, ``/health`` stay public: they expose
    no node data.
    """
    database = Path(database)
    # One full init (schema, migrations, WAL); requests then open light connections.
    NodeStore(database).close()

    def profiles() -> dict[str, object]:
        # Re-read on each request so edits to profiles.yaml apply without restart.
        return {item.name: item for item in load_profiles(profiles_path)}

    runner = CycleRunner(cycle, interval_minutes) if cycle is not None else None
    root = Path(client_root) if client_root is not None else Path.cwd()
    config = config or load_config(root / "config" / "squad.yaml")
    log = logging.getLogger("squad_vpn.server")
    keystore = KeyStore(root / "data" / "api_keys.json")
    limiter = RateLimiter()
    cache = TtlCache()
    backups_dir = root / "data" / "backups"

    async def after_cycle() -> None:
        from .backup import backup_due, create_backup

        cache.invalidate()
        if backup_due(backups_dir, every_hours=config.backup.every_hours):
            try:
                path = await asyncio.to_thread(
                    create_backup, database, backups_dir, keep=config.backup.keep
                )
                log.info("Резервная копия базы: %s", path.name)
            except Exception as exc:
                log.warning("Резервная копия не создана: %s", exc)

    if runner is not None:
        runner.on_finish = after_cycle
    if client is None:
        from .client import VpnClient

        client = VpnClient(
            database,
            root=root,
            profiles_path=Path(profiles_path) if profiles_path else None,
            binary=cycle.binary if cycle is not None else DEFAULT_BINARY,
            log=logging.getLogger("squad_vpn.client").info,
        )
    vpn = client

    def client_settings():
        from .settings import load_settings

        return load_settings(root / "data" / "settings.json")

    background: set[asyncio.Task] = set()  # keep references: tasks must not be GC'd

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(runner.loop()) if runner is not None else None
        # Reconnect after a restart/update, or at Windows logon if asked to.
        settings = client_settings()
        resume = vpn.state.load().get("connected")
        if settings.client_autoconnect or resume:
            profile = str(vpn.state.load().get("profile") or settings.client_profile)
            connecting = asyncio.create_task(vpn.connect(profile))
            background.add(connecting)
            connecting.add_done_callback(background.discard)
        try:
            yield
        finally:
            try:
                await vpn.disconnect("shutdown", keep_resume=True)
            except Exception:
                pass
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(
        lifespan=lifespan,
        title="SQUAD VPN",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    def supplied_token(request: Request) -> str:
        supplied = request.query_params.get("token") or ""
        header = request.headers.get("authorization") or ""
        if not supplied and header.lower().startswith("bearer "):
            supplied = header[7:].strip()
        return supplied

    def authorize(needed: str):
        """Dependency: legacy --token (full access) or an API key with the scope.

        This computer itself needs no key; the network does, as soon as a
        token or any key is configured.
        """

        def dependency(request: Request) -> None:
            host = _client_host(request)
            if limiter.blocked_for(host):
                raise HTTPException(status_code=429, detail="Слишком много неверных ключей, попробуй позже")
            supplied = supplied_token(request)
            if supplied:
                if token and secrets.compare_digest(supplied.encode(), token.encode()):
                    return
                key = keystore.match(supplied)
                if key is not None:
                    if allows(key.scope, needed):
                        return
                    raise HTTPException(
                        status_code=403, detail=f"У ключа «{key.name}» нет прав на это ({key.scope})"
                    )
                if host not in REAL_LOOPBACK:
                    limiter.auth_failure(
                        host, config.rate_limit.auth_failures_per_minute,
                        config.rate_limit.block_minutes * 60,
                    )
                raise HTTPException(status_code=401, detail="Неверный ключ доступа")
            if host in REAL_LOOPBACK:
                return
            if not token and not keystore.load():
                return
            raise HTTPException(status_code=401, detail="Нужен ключ доступа (?token=...)")

        return dependency

    require_token = authorize("read")

    def get_store() -> Iterator[NodeStore]:
        store = NodeStore(database, init_schema=False)
        try:
            yield store
        finally:
            store.close()

    protected = [Depends(authorize("read"))]

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        return _dashboard_html()

    @app.get("/app", response_class=HTMLResponse, include_in_schema=False)
    def desktop_app() -> str:
        return _dashboard_html("app.html")

    local_only = [Depends(require_token), Depends(_require_local)]

    @app.get("/api/links", dependencies=protected)
    def links(request: Request, store: NodeStore = Depends(get_store)) -> dict[str, object]:
        from .publish import PublishTarget, detect_origin

        origin = detect_origin(root)
        target = PublishTarget(origin, branch="subs") if origin else None
        items = []
        for profile in profiles().values():
            items.append(
                {
                    "name": profile.name,
                    "description": profile.description,
                    "count": len(select_profile(store, profile)),
                }
            )
        return {
            "github_raw": target.raw_base() if target else None,
            "github_cdn": target.cdn_base() if target else None,
            "local": str(request.base_url).rstrip("/") + "/sub",
            "lan": _lan_sub(request),
            "profiles": items,
        }

    def _lan_sub(request: Request) -> str | None:
        settings = client_settings()
        address = lan_address()
        if not settings.lan_access or address is None or not keystore.load():
            return None
        return f"http://{address}:{request.url.port or 8080}/sub"

    # --- access keys, backups, diagnostics (this computer only) ----------

    @app.get("/api/keys", dependencies=local_only)
    def keys_list() -> dict[str, object]:
        return {
            "keys": [key.public() for key in keystore.load()],
            "scopes": list(SCOPES),
            "lan_address": lan_address(),
        }

    @app.post("/api/keys", dependencies=local_only)
    def keys_create(payload: dict[str, object]) -> dict[str, object]:
        try:
            key, secret = keystore.create(str(payload.get("name") or ""), str(payload.get("scope") or "sub"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"key": key.public(), "token": secret}

    @app.delete("/api/keys/{name}", dependencies=local_only)
    def keys_revoke(name: str) -> dict[str, object]:
        if not keystore.revoke(name):
            raise HTTPException(status_code=404, detail="Нет такого ключа")
        return {"ok": True}

    @app.get("/api/backups", dependencies=local_only)
    def backups_list() -> dict[str, object]:
        from .backup import list_backups

        return {
            "backups": list_backups(backups_dir),
            "every_hours": config.backup.every_hours,
            "keep": config.backup.keep,
        }

    @app.post("/api/backups", dependencies=local_only)
    async def backups_create() -> dict[str, object]:
        from .backup import create_backup

        path = await asyncio.to_thread(create_backup, database, backups_dir, keep=config.backup.keep)
        return {"name": path.name}

    @app.post("/api/backups/{name}/restore", dependencies=local_only)
    def backups_restore(name: str) -> dict[str, object]:
        """Restoring a live database is unsafe: ask the agent to do it on restart."""
        from .agent import send_command
        from .backup import list_backups

        if name not in {item["name"] for item in list_backups(backups_dir)}:
            raise HTTPException(status_code=404, detail="Нет такой копии")
        request_file = root / "data" / "restore-request.json"
        request_file.write_text(json.dumps({"name": name}), encoding="utf-8")
        if not send_command("restart"):
            request_file.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail="Фоновая программа не запущена")
        return {"ok": True, "restarting": True}

    @app.get("/api/doctor", dependencies=local_only)
    async def doctor() -> dict[str, object]:
        from .diagnostics import run_checks

        binary = cycle.binary if cycle is not None else DEFAULT_BINARY
        last = runner.last if runner is not None else None
        checks = await asyncio.to_thread(
            run_checks, root, database, binary,
            client_connected=vpn.status.get("state") == "connected",
            last_cycle=(last or {}) if runner is not None else None,
        )
        worst = "error" if any(c["status"] == "error" for c in checks) else (
            "warn" if any(c["status"] == "warn" for c in checks) else "ok"
        )
        return {"status": worst, "checks": checks}

    @app.post("/api/doctor/fix/{fix}", dependencies=local_only)
    async def doctor_fix(fix: Literal["restore_proxy", "backup_now"]) -> dict[str, object]:
        if fix == "restore_proxy":
            from .client import cleanup_orphan

            if vpn.status.get("state") == "connected":
                await vpn.disconnect("doctor")
            return await asyncio.to_thread(cleanup_orphan, root, clear_resume=True)
        from .backup import create_backup

        path = await asyncio.to_thread(create_backup, database, backups_dir, keep=config.backup.keep)
        return {"name": path.name}

    @app.get("/api/qr", dependencies=protected)
    def qr(text: str = Query(..., min_length=1, max_length=1000)) -> Response:
        import io

        import qrcode
        import qrcode.image.svg

        image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=2)
        buffer = io.BytesIO()
        image.save(buffer)
        return Response(buffer.getvalue(), media_type="image/svg+xml")

    @app.get("/api/logs", dependencies=local_only)
    def logs(
        name: Literal["agent", "server", "crash", "app"] = "agent",
        lines: int = Query(200, ge=1, le=2000),
    ) -> dict[str, object]:
        path = root / "data" / "logs" / LOG_FILES[name]
        return {"name": name, "lines": _tail(path, lines)}

    @app.get("/api/settings", dependencies=local_only)
    def get_settings() -> dict[str, object]:
        from .settings import ALLOWED_INTERVALS, load_settings

        settings = load_settings(root / "data" / "settings.json")
        return {**asdict(settings), "allowed_intervals": list(ALLOWED_INTERVALS)}

    @app.post("/api/settings", dependencies=local_only)
    def set_settings(payload: dict[str, object]) -> dict[str, object]:
        from .settings import Settings, load_settings, save_settings

        path = root / "data" / "settings.json"
        current = asdict(load_settings(path))
        current.update({k: v for k, v in payload.items() if k in current})
        try:
            saved = save_settings(Settings(**current), path)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {**asdict(saved), "restart_required": True}

    @app.get("/api/autostart", dependencies=local_only)
    def autostart_status() -> dict[str, object]:
        import os as _os

        from . import autostart

        if _os.name != "nt":
            return {"supported": False, "enabled": False}
        return {"supported": True, "enabled": autostart.is_enabled()}

    @app.post("/api/autostart", dependencies=local_only)
    def autostart_set(payload: dict[str, object]) -> dict[str, object]:
        from . import autostart

        try:
            if payload.get("enabled"):
                autostart.enable(root)
            else:
                autostart.disable()
        except OSError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"supported": True, "enabled": bool(payload.get("enabled"))}

    @app.post("/api/control/{command}", dependencies=local_only)
    def control(command: Literal["update", "restart", "open-folder"]) -> dict[str, object]:
        from .agent import send_command

        if command == "open-folder":
            import os as _os

            if _os.name != "nt":
                raise HTTPException(status_code=409, detail="Только в Windows")
            _os.startfile(root)  # type: ignore[attr-defined]
            return {"ok": True}
        if not send_command(command):
            raise HTTPException(status_code=409, detail="Агент не запущен")
        return {"ok": True}

    # The commit this server process runs: the app reloads when it changes.
    from . import ota

    build = ota.git_head(root)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "version": __version__, "commit": build, "auth": bool(token)}

    @app.get("/api/update", dependencies=protected)
    def update_status() -> dict[str, object]:
        from .appdist import LOCAL_VERSION
        from .diagnostics import _port_open

        journal = ota.Journal(root)
        settings = client_settings()
        try:
            app_version = (root / LOCAL_VERSION).read_text(encoding="utf-8").strip() or None
        except OSError:
            app_version = None
        return {
            "version": __version__,
            "commit": build,
            "disk_commit": ota.git_head(root),
            "auto_update": settings.auto_update,
            "update_hours": settings.update_hours,
            "agent_running": _port_open(8079),
            "last_check": journal.data.get("last_check"),
            "next_check": journal.data.get("next_check"),
            "message": journal.data.get("message"),
            "history": list(reversed(journal.history))[:10],
            "app_version": app_version,
            "changelog": ota.changelog(root, 3),
        }

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        """Block DNS rebinding (foreign Host) and CSRF (foreign Origin on changes)."""
        hostname = (request.url.hostname or "")
        if not _host_allowed(hostname):
            return JSONResponse({"detail": "Недопустимое имя хоста"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != "null":
                from urllib.parse import urlsplit

                parts = urlsplit(origin)
                same = (parts.hostname or "") == hostname and (parts.port or 80) == (request.url.port or 80)
                if not same or not _host_allowed(parts.hostname or ""):
                    return JSONResponse({"detail": "Запрос с чужого сайта отклонён"}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        host = _client_host(request)
        path = request.url.path
        if host not in REAL_LOOPBACK and (path == "/sub" or path.startswith("/api/")):
            limits = config.rate_limit
            bucket, limit = ("sub", limits.sub_per_minute) if path == "/sub" else ("api", limits.api_per_minute)
            wait = limiter.blocked_for(host) or limiter.hit(host, bucket, limit)
            if wait:
                return JSONResponse(
                    {"detail": "Слишком много запросов, подожди немного"},
                    status_code=429,
                    headers={"Retry-After": str(int(wait) + 1)},
                )
        return await call_next(request)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if exc.status_code == 404 and detail == "Not Found":
            detail = "Не найдено"
        elif exc.status_code == 405:
            detail = "Этот метод здесь не поддерживается"
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def crash(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Ошибка при обработке %s %s", request.method, request.url.path)
        return JSONResponse(
            {"detail": f"Внутренняя ошибка ({type(exc).__name__}). Подробности в журнале data/logs/squad.log"},
            status_code=500,
        )

    @app.get("/sub", dependencies=[Depends(authorize("sub"))])
    def subscription(
        request: Request,
        store: NodeStore = Depends(get_store),
        profile: str | None = None,
        country: str | None = None,
        protocol: str | None = None,
        min_score: float | None = Query(None, ge=0, le=100),
        min_stability: float | None = Query(None, ge=0, le=100),
        max_latency: float | None = Query(None, gt=0),
        checked_within_hours: int | None = Query(None, ge=1),
        seen_within_hours: int | None = Query(None, ge=1),
        limit: int | None = Query(None, ge=1, le=MAX_SUB_LIMIT),
        format: Literal["plain", "base64", "mihomo"] = "plain",
    ) -> Response:
        cache_key = ("sub", tuple(sorted(
            (k, v) for k, v in request.query_params.items() if k != "token"
        )))
        cached = cache.get(cache_key)
        if cached is not None:
            body, media_type, headers = cached  # type: ignore[misc]
            return Response(body, media_type=media_type, headers=headers)
        available = profiles()
        if profile is not None and profile not in available:
            raise HTTPException(
                status_code=404,
                detail=f"Неизвестный профиль. Доступны: {', '.join(available)}",
            )
        # Profile supplies defaults, explicit query parameters override them.
        base = available.get(profile or "", replace(GROUP_PROFILE, name="custom"))
        overrides: dict[str, object] = {
            "min_score": min_score,
            "min_stability": min_stability,
            "max_latency": max_latency,
            "checked_within_hours": checked_within_hours,
            "seen_within_hours": seen_within_hours,
            "limit": limit,
            "countries": (country,) if country else None,
            "protocols": (protocol,) if protocol else None,
        }
        chosen = replace(base, **{k: v for k, v in overrides.items() if v is not None})
        records = select_profile(store, chosen)
        rendered = render_subscription(
            records, load_branding(branding_path), chosen.name, chosen.description
        )
        headers = {
            **rendered.headers,
            "x-squad-nodes": str(len(records)),
            "cache-control": "no-store",
        }
        if format == "mihomo":
            body = rendered.mihomo
            media_type = "text/yaml; charset=utf-8"
        else:
            body = rendered.base64 if format == "base64" else rendered.plain
            media_type = "text/plain; charset=utf-8"
        cache.set(cache_key, (body, media_type, headers), config.cache.sub_seconds)
        return Response(body, media_type=media_type, headers=headers)

    @app.get("/api/profiles", dependencies=protected)
    def profiles_list() -> dict[str, object]:
        return {name: asdict(item) for name, item in profiles().items()}

    @app.get("/api/nodes", dependencies=protected)
    def nodes(
        store: NodeStore = Depends(get_store),
        alive_only: bool = False,
        country: str | None = None,
        protocol: str | None = None,
        min_score: float = Query(0.0, ge=0, le=100),
        min_stability: float = Query(0.0, ge=0, le=100),
        max_latency: float | None = Query(None, gt=0),
        sort: str = "score",
        limit: int = Query(50, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(0, ge=0),
    ) -> dict[str, object]:
        if sort not in SORT_COLUMNS:
            raise HTTPException(
                status_code=422,
                detail=f"sort должен быть одним из: {', '.join(SORT_COLUMNS)}",
            )
        filters = {
            "alive_only": alive_only,
            "country": country,
            "protocol": protocol,
            "min_score": min_score,
            "min_stability": min_stability,
            "max_latency": max_latency,
        }
        records = store.list_ranked(**filters, sort=sort, limit=limit, offset=offset)
        return {
            "total": store.count_ranked(**filters),
            "limit": limit,
            "offset": offset,
            "items": [ranked_to_dict(item) for item in records],
        }

    @app.get("/api/nodes/{fingerprint}", dependencies=protected)
    def node_detail(
        fingerprint: str,
        store: NodeStore = Depends(get_store),
        history: int = Query(50, ge=1, le=500),
    ) -> dict[str, object]:
        record = store.get_ranked(fingerprint)
        if record is None:
            raise HTTPException(status_code=404, detail="Узел не найден")
        payload = ranked_to_dict(record)
        payload["history"] = store.node_history(fingerprint, limit=history)
        return payload

    @app.get("/api/stats", dependencies=protected)
    def stats(store: NodeStore = Depends(get_store)) -> dict[str, object]:
        cached = cache.get("stats")
        if cached is not None:
            return cached  # type: ignore[return-value]
        payload = store.stats()
        payload["version"] = __version__
        cache.set("stats", payload, config.cache.stats_seconds)
        return payload

    @app.get("/api/cycle", dependencies=protected)
    def cycle_status() -> dict[str, object]:
        if runner is None:
            return {"enabled": False}
        return runner.status()

    @app.post("/api/cycle/run", dependencies=[Depends(authorize("admin"))])
    def cycle_run() -> dict[str, object]:
        if runner is None:
            raise HTTPException(
                status_code=409, detail="Фоновый цикл выключен (запусти serve --watch)"
            )
        return {"started": runner.trigger()}

    @app.get("/api/probes", dependencies=protected)
    def probes_list(store: NodeStore = Depends(get_store)) -> list[dict[str, object]]:
        return store.list_probes()

    @app.get("/api/agent", dependencies=protected)
    def agent_status() -> dict[str, object]:
        from .agent import read_status

        from .diagnostics import _port_open

        status = read_status(root) or {}
        # agent.json survives a stop; whether the agent runs is told by its port.
        return {**status, "running": _port_open(8079)}

    @app.get("/api/client", dependencies=local_only)
    def client_status(store: NodeStore = Depends(get_store)) -> dict[str, object]:
        settings = client_settings()
        return {
            **vpn.snapshot(),
            "proxy_supported": vpn.backend.supported,
            "port": vpn.mixed_port,
            "settings": {
                "profile": settings.client_profile,
                "autoconnect": settings.client_autoconnect,
            },
            "totals": store.client_totals(),
        }

    @app.post("/api/client/connect", dependencies=local_only)
    async def client_connect(payload: dict[str, object] | None = None) -> dict[str, object]:
        from .settings import save_settings

        settings = client_settings()
        profile = str((payload or {}).get("profile") or settings.client_profile)
        if profile not in profiles():
            raise HTTPException(status_code=422, detail="Неизвестный профиль")
        if profile != settings.client_profile:
            settings.client_profile = profile
            save_settings(settings, root / "data" / "settings.json")
        return await vpn.connect(profile)

    @app.post("/api/client/disconnect", dependencies=local_only)
    async def client_disconnect() -> dict[str, object]:
        return await vpn.disconnect("user")

    @app.post("/api/client/failover", dependencies=local_only)
    async def client_failover() -> dict[str, object]:
        try:
            return await vpn.failover()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/client/choose", dependencies=local_only)
    async def client_choose(payload: dict[str, object]) -> dict[str, object]:
        node = payload.get("node")
        try:
            return await vpn.choose(str(node) if node else None)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/client/nodes", dependencies=local_only)
    def client_nodes() -> list[dict[str, object]]:
        return vpn.node_names()

    @app.get("/api/client/events", dependencies=local_only)
    def client_events(
        limit: int = Query(30, ge=1, le=200), store: NodeStore = Depends(get_store)
    ) -> list[dict[str, object]]:
        return store.client_events(limit)

    @app.get("/api/sources", dependencies=protected)
    def sources(store: NodeStore = Depends(get_store)) -> list[dict[str, object]]:
        rows = store.list_source_status()
        for row in rows:
            try:
                row["tags"] = json.loads(str(row.pop("tags_json") or "[]"))
            except ValueError:
                row["tags"] = []
        return rows

    return app


def serve(
    database: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    token: str | None = None,
    cycle: CycleOptions | None = None,
    interval_minutes: int = 60,
    profiles_path: str | Path | None = DEFAULT_PROFILES_PATH,
) -> None:
    import uvicorn

    from .logsetup import setup_logging

    config = load_config()
    setup_logging(Path.cwd(), config.logging)
    app = create_app(
        database,
        token=token,
        cycle=cycle,
        interval_minutes=interval_minutes,
        profiles_path=profiles_path,
        config=config,
    )
    logging.getLogger("squad_vpn.server").info("SQUAD VPN %s слушает %s:%s", __version__, host, port)
    # Access lines ("GET /api/stats 200") are noise for a desktop app.
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)
