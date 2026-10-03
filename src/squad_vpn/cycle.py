from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .collector import collect_source_specs
from .exporter import export_ranked_catalog, export_sources
from .publish import PublishTarget, publish
from .smart import export_smart_catalog
from .sources import load_source_specs
from .store import NodeStore
from .validator import DEFAULT_BINARY, DEFAULT_TEST_URL, MihomoValidator


Log = Callable[[str], None]


@dataclass(slots=True)
class CycleOptions:
    sources: Path = Path("config/sources.yaml")
    database: Path = Path("data/squad_vpn.sqlite3")
    output: Path = Path("data/output")
    source_concurrency: int = 12
    binary: Path = DEFAULT_BINARY
    test_url: str = DEFAULT_TEST_URL
    timeout_ms: int = 5000
    validation_concurrency: int = 16
    geo_limit: int = 10
    limit: int = 200
    recheck_minutes: int = 60
    install_mihomo: bool = True
    cleanup: bool = True
    unseen_days: int = 3
    publish: PublishTarget | None = None


@dataclass(slots=True)
class CycleReport:
    started_at: str = ""
    finished_at: str | None = None
    duration_s: float | None = None
    steps: dict[str, dict[str, object]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "ok": self.ok,
            "steps": self.steps,
            "errors": self.errors,
        }


async def collect_step(
    sources: Path,
    database: Path,
    *,
    concurrency: int = 12,
    log: Log = print,
) -> dict[str, object]:
    specs = load_source_specs(sources)
    if not specs:
        log(f"Нет включённых источников в {sources}")
        return {"sources": 0, "ok": 0, "nodes": 0}
    nodes, reports = await collect_source_specs(specs, concurrency=concurrency)
    store = NodeStore(database)
    try:
        saved = store.upsert_many(nodes)
        for report in reports:
            store.record_source_report(report)
        store.prune_sources([spec.name for spec in specs])
    finally:
        store.close()

    ok = sum(report.ok for report in reports)
    log(f"Источников: {len(reports)}; успешно: {ok}; ошибок: {len(reports) - ok}")
    log(f"Собрано уникальных узлов: {len(nodes)}")
    log(f"Записано в базу: {saved}")
    for report in reports:
        state = "OK" if report.ok else "ERR"
        log(
            f"  [{state}] {report.source.name}: "
            f"{report.nodes_selected}/{report.nodes_found} узлов, "
            f"{report.duration_ms:.0f} ms"
        )
        if report.error:
            log(f"       {report.error}")
    return {"sources": len(reports), "ok": ok, "nodes": len(nodes)}


async def validate_step(
    database: Path,
    *,
    binary: Path = DEFAULT_BINARY,
    test_url: str = DEFAULT_TEST_URL,
    timeout_ms: int = 5000,
    concurrency: int = 16,
    geo_limit: int = 10,
    limit: int | None = 200,
    recheck_minutes: int = 60,
    log: Log = print,
) -> dict[str, object]:
    if not Path(binary).exists():
        raise FileNotFoundError(
            f"Mihomo не найден: {binary}. Выполни squad-vpn setup-mihomo"
        )
    store = NodeStore(database)
    try:
        nodes = store.list_validation_candidates(
            recheck_after_minutes=recheck_minutes, limit=limit
        )
        if not nodes:
            log("Нет узлов, которым сейчас нужна проверка")
            return {"checked": 0, "alive": 0}
        validator = MihomoValidator(binary, test_url=test_url, timeout_ms=timeout_ms)
        results = await validator.validate(
            nodes, concurrency=concurrency, geo_limit=geo_limit
        )
        alive = 0
        for result in results:
            store.record_validation(result)
            alive += int(result.alive)
        store.prune_history()
    finally:
        store.close()
    log(f"Проверено через Mihomo: {len(results)}")
    log(f"Живых: {alive}; мёртвых: {len(results) - alive}")
    return {"checked": len(results), "alive": alive}


def cleanup_step(database: Path, *, unseen_days: int = 3, log: Log = print) -> dict[str, int]:
    store = NodeStore(database)
    try:
        removed = store.cleanup(unseen_days=unseen_days)
    finally:
        store.close()
    log(
        f"Очистка: удалено {removed['total']} "
        f"(пропали из источников: {removed['unseen']}, "
        f"мёртвые и пропавшие: {removed['dead_unseen']})"
    )
    return removed


def export_step(database: Path, output: Path, *, log: Log = print) -> dict[str, object]:
    store = NodeStore(database)
    try:
        records = store.list_ranked()
        export_ranked_catalog(records, output)
        export_sources(store.list_source_status(), output / "sources.json")
        index = export_smart_catalog(store, output / "smart")
    finally:
        store.close()
    alive = sum(item.alive is True for item in records)
    log(f"Экспортировано узлов: {len(records)}; живых: {alive} -> {output}")
    return {
        "nodes": len(records),
        "alive": alive,
        "profiles": {
            name: meta["count"]  # type: ignore[index]
            for name, meta in index["profiles"].items()  # type: ignore[union-attr]
        },
    }


def publish_step(database: Path, target: PublishTarget, *, log: Log = print) -> dict[str, object]:
    store = NodeStore(database)
    try:
        result = publish(store, target)
    finally:
        store.close()
    log(f"Опубликовано в ветку {target.branch}: {result['raw_base']}")
    return result


async def _install(binary: Path, log: Log) -> dict[str, object]:
    from .setup_mihomo import install_mihomo

    target, version = await install_mihomo(binary)
    log(f"Mihomo {version} установлен: {target}")
    return {"version": version}


async def run_cycle(options: CycleOptions, *, log: Log = print) -> CycleReport:
    """collect -> validate -> cleanup -> export -> publish.

    A failing step is recorded and the remaining steps still run, so
    subscriptions are refreshed from existing data even if, say, Mihomo is
    missing or every source is down.
    """
    report = CycleReport(started_at=datetime.now(UTC).isoformat(timespec="seconds"))
    started = time.monotonic()

    async def step(name: str, func, *, blocking: bool = False) -> None:
        try:
            if blocking:
                # Keep the event loop (and the API in `serve --watch`) responsive.
                result = await asyncio.to_thread(func)
            else:
                result = await func()
            report.steps[name] = result
        except Exception as exc:  # one broken step must not stop the cycle
            report.errors.append(f"{name}: {exc}")
            report.steps[name] = {"error": str(exc)}
            log(f"Шаг {name} пропущен: {exc}")

    await step(
        "collect",
        lambda: collect_step(
            options.sources,
            options.database,
            concurrency=options.source_concurrency,
            log=log,
        ),
    )
    if options.install_mihomo and not Path(options.binary).exists():
        await step("setup_mihomo", lambda: _install(options.binary, log))
    await step(
        "validate",
        lambda: validate_step(
            options.database,
            binary=options.binary,
            test_url=options.test_url,
            timeout_ms=options.timeout_ms,
            concurrency=options.validation_concurrency,
            geo_limit=options.geo_limit,
            limit=options.limit,
            recheck_minutes=options.recheck_minutes,
            log=log,
        ),
    )
    if options.cleanup:
        await step(
            "cleanup",
            lambda: cleanup_step(options.database, unseen_days=options.unseen_days, log=log),
            blocking=True,
        )
    await step(
        "export",
        lambda: export_step(options.database, options.output, log=log),
        blocking=True,
    )
    if options.publish is not None:
        target = options.publish
        await step(
            "publish",
            lambda: publish_step(options.database, target, log=log),
            blocking=True,
        )

    report.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    report.duration_s = round(time.monotonic() - started, 1)
    return report
