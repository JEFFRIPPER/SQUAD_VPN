from __future__ import annotations

import asyncio
import base64
import json
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from . import __version__
from .cycle import CycleOptions, run_cycle
from .exporter import ranked_to_dict, render_mihomo, render_plain
from .smart import DEFAULT_PROFILES_PATH, GROUP_PROFILE, load_profiles, select_profile
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
LOG_FILES = {"agent": "agent.log", "server": "server.log"}


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

    @staticmethod
    def _log(message: str) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)

    async def run_once(self) -> None:
        async with self._lock:
            self.running = True
            try:
                report = await run_cycle(self.options, log=self._log)
                self.last = report.as_dict()
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(runner.loop()) if runner is not None else None
        try:
            yield
        finally:
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

    def require_token(request: Request) -> None:
        if not token:
            return
        supplied = request.query_params.get("token") or ""
        header = request.headers.get("authorization") or ""
        if header.lower().startswith("bearer "):
            supplied = supplied or header[7:].strip()
        if not secrets.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="Нужен корректный token")

    def get_store() -> Iterator[NodeStore]:
        store = NodeStore(database, init_schema=False)
        try:
            yield store
        finally:
            store.close()

    protected = [Depends(require_token)]

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        return _dashboard_html()

    @app.get("/app", response_class=HTMLResponse, include_in_schema=False)
    def desktop_app() -> str:
        return _dashboard_html("app.html")

    local_only = [Depends(require_token), Depends(_require_local)]

    @app.get("/api/links", dependencies=protected)
    def links(request: Request, store: NodeStore = Depends(get_store)) -> dict[str, object]:
        from .agent import project_root
        from .publish import PublishTarget, detect_origin

        origin = detect_origin(project_root())
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
            "profiles": items,
        }

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
        name: Literal["agent", "server"] = "agent",
        lines: int = Query(200, ge=1, le=2000),
    ) -> dict[str, object]:
        from .agent import project_root

        path = project_root() / "data" / "logs" / LOG_FILES[name]
        return {"name": name, "lines": _tail(path, lines)}

    @app.get("/api/settings", dependencies=local_only)
    def get_settings() -> dict[str, object]:
        from .agent import project_root
        from .settings import ALLOWED_INTERVALS, load_settings

        settings = load_settings(project_root() / "data" / "settings.json")
        return {**asdict(settings), "allowed_intervals": list(ALLOWED_INTERVALS)}

    @app.post("/api/settings", dependencies=local_only)
    def set_settings(payload: dict[str, object]) -> dict[str, object]:
        from .agent import project_root
        from .settings import Settings, load_settings, save_settings

        path = project_root() / "data" / "settings.json"
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
        from .agent import project_root

        try:
            if payload.get("enabled"):
                autostart.enable(project_root())
            else:
                autostart.disable()
        except OSError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"supported": True, "enabled": bool(payload.get("enabled"))}

    @app.post("/api/control/{command}", dependencies=local_only)
    def control(command: Literal["update", "restart", "open-folder"]) -> dict[str, object]:
        from .agent import project_root, send_command

        if command == "open-folder":
            import os as _os

            if _os.name != "nt":
                raise HTTPException(status_code=409, detail="Только в Windows")
            _os.startfile(project_root())  # type: ignore[attr-defined]
            return {"ok": True}
        if not send_command(command):
            raise HTTPException(status_code=409, detail="Агент не запущен")
        return {"ok": True}

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "version": __version__, "auth": bool(token)}

    @app.get("/sub", dependencies=protected)
    def subscription(
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
        nodes = [item.node for item in records]
        headers = {
            "profile-update-interval": "1",
            "x-squad-nodes": str(len(nodes)),
            "cache-control": "no-store",
        }
        if format == "mihomo":
            return Response(
                render_mihomo(nodes, f"SQUAD {chosen.name}"),
                media_type="text/yaml; charset=utf-8",
                headers=headers,
            )
        body = render_plain(nodes)
        if format == "base64":
            body = base64.b64encode(body.encode("utf-8")).decode("ascii")
        return PlainTextResponse(body, headers=headers)

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
        payload = store.stats()
        payload["version"] = __version__
        return payload

    @app.get("/api/cycle", dependencies=protected)
    def cycle_status() -> dict[str, object]:
        if runner is None:
            return {"enabled": False}
        return runner.status()

    @app.post("/api/cycle/run", dependencies=protected)
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

        status = read_status()
        return {"running": False} if status is None else {"running": True, **status}

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

    app = create_app(
        database,
        token=token,
        cycle=cycle,
        interval_minutes=interval_minutes,
        profiles_path=profiles_path,
    )
    uvicorn.run(app, host=host, port=port, log_level="warning")
