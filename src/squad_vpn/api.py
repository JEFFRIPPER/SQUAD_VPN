from __future__ import annotations

import base64
import json
import secrets
from collections.abc import Iterator
from dataclasses import asdict
from importlib import resources
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from . import __version__
from .exporter import ranked_to_dict, render_mihomo, render_plain
from .smart import DEFAULT_PROFILES, SmartProfile
from .store import SORT_COLUMNS, NodeStore


PROFILES: dict[str, SmartProfile] = {item.name: item for item in DEFAULT_PROFILES}
MAX_SUB_LIMIT = 2000
MAX_PAGE_LIMIT = 500


def _dashboard_html() -> str:
    return (
        resources.files("squad_vpn")
        .joinpath("dashboard/index.html")
        .read_text(encoding="utf-8")
    )


def create_app(database: str | Path, *, token: str | None = None) -> FastAPI:
    """Build the HTTP API.

    When ``token`` is set, ``/sub`` and ``/api/*`` require it either as
    ``?token=`` (subscription clients cannot send headers) or as
    ``Authorization: Bearer``. ``/``, ``/health`` stay public: they expose
    no node data.
    """
    database = Path(database)
    # One full init (schema, migrations, WAL); requests then open light connections.
    NodeStore(database).close()

    app = FastAPI(
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
        if profile is not None and profile not in PROFILES:
            raise HTTPException(
                status_code=404,
                detail=f"Неизвестный профиль. Доступны: {', '.join(PROFILES)}",
            )
        # Profile supplies defaults, explicit query parameters override them.
        base = PROFILES.get(profile or "", SmartProfile("custom"))
        records = store.list_ranked(
            alive_only=True,
            min_score=base.min_score if min_score is None else min_score,
            min_stability=base.min_stability if min_stability is None else min_stability,
            max_latency=base.max_latency if max_latency is None else max_latency,
            country=country,
            protocol=protocol,
            checked_within_hours=(
                base.checked_within_hours
                if checked_within_hours is None
                else checked_within_hours
            ),
            seen_within_hours=(
                base.seen_within_hours if seen_within_hours is None else seen_within_hours
            ),
            limit=base.limit if limit is None else limit,
        )
        nodes = [item.node for item in records]
        headers = {
            "profile-update-interval": "1",
            "x-squad-nodes": str(len(nodes)),
            "cache-control": "no-store",
        }
        if format == "mihomo":
            return Response(
                render_mihomo(nodes),
                media_type="text/yaml; charset=utf-8",
                headers=headers,
            )
        body = render_plain(nodes)
        if format == "base64":
            body = base64.b64encode(body.encode("utf-8")).decode("ascii")
        return PlainTextResponse(body, headers=headers)

    @app.get("/api/profiles", dependencies=protected)
    def profiles() -> dict[str, object]:
        return {name: asdict(item) for name, item in PROFILES.items()}

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
) -> None:
    import uvicorn

    uvicorn.run(create_app(database, token=token), host=host, port=port, log_level="info")
