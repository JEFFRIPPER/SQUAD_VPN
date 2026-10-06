from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .collector import collect_source_specs
from .exporter import export_ranked_catalog, export_sources
from .probe import (
    IDENTITY_FILE,
    ProbeIdentity,
    default_kind,
    load_identity,
    publish_report,
    sync_probes,
)
from .publish import PublishTarget, detect_origin, publish
from .smart import DEFAULT_PROFILES_PATH, export_smart_catalog, groups_enabled, load_profiles
from .sources import load_source_specs
from .store import NodeStore
from .validator import (
    DEFAULT_BINARY,
    DEFAULT_DOWNLOAD_BYTES,
    DEFAULT_TEST_URL,
    DOWNLOAD_FAILED,
    MihomoValidator,
)


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
    download_bytes: int = DEFAULT_DOWNLOAD_BYTES
    validation_concurrency: int = 16
    geo_limit: int = 10
    limit: int = 200
    recheck_minutes: int = 60
    install_mihomo: bool = True
    cleanup: bool = True
    # Refresh the Russian mobile white lists (for the "whitelist" subscription).
    whitelist: bool = True
    unseen_days: int = 3
    publish: PublishTarget | None = None
    profiles: Path | None = DEFAULT_PROFILES_PATH
    # Probe network (v0.7): own id/region overrides, exchange of reports.
    probe_id: str | None = None
    probe_region: str | None = None
    probe_sync: bool = True
    probe_publish: bool = False
    probe_repo: str | None = None
    probe_identity_file: Path = IDENTITY_FILE

    def resolve_probe_repo(self) -> str | None:
        if self.probe_repo:
            return self.probe_repo
        if self.publish is not None:
            return self.publish.repo
        return os.environ.get("SQUAD_PUBLISH_REPO") or detect_origin()


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
    log(f"Собрано уникальных серверов: {len(nodes)}")
    log(f"Записано в базу: {saved}")
    for report in reports:
        state = "OK" if report.ok else "ERR"
        log(
            f"  [{state}] {report.source.name}: "
            f"{report.nodes_selected}/{report.nodes_found} серверов, "
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
    download_bytes: int = DEFAULT_DOWNLOAD_BYTES,
    concurrency: int = 16,
    geo_limit: int = 10,
    limit: int | None = 200,
    recheck_minutes: int = 60,
    probe: ProbeIdentity | None = None,
    log: Log = print,
) -> dict[str, object]:
    if not Path(binary).exists():
        raise FileNotFoundError(
            f"Mihomo не найден: {binary}. Выполни squad-vpn setup-mihomo"
        )
    store = NodeStore(database)
    try:
        if probe is not None:
            store.register_probe(probe.probe_id, probe.region, kind=probe.kind, version=__version__)
        nodes = store.list_validation_candidates(
            recheck_after_minutes=recheck_minutes, limit=limit
        )
        if not nodes:
            log("Нет серверов, которым сейчас нужна проверка")
            return {"checked": 0, "alive": 0}
        validator = MihomoValidator(
            binary, test_url=test_url, timeout_ms=timeout_ms, download_bytes=download_bytes
        )
        geo_known = store.fingerprints_with_country()
        results = await validator.validate(
            nodes, concurrency=concurrency, geo_limit=geo_limit, geo_known=geo_known
        )
        alive = 0
        for result in results:
            if probe is not None:
                result.probe_id = probe.probe_id
            store.record_validation(result)
            alive += int(result.alive)
        store.prune_history()
    finally:
        store.close()
    log(f"Проверено через Mihomo: {len(results)}")
    log(f"Живых: {alive}; мёртвых: {len(results) - alive}")
    stalled = sum(
        1 for result in results if (result.error or "").startswith(DOWNLOAD_FAILED)
    )
    if download_bytes > 0:
        log(f"Отсеяно проверкой загрузки (пинг есть, данные не идут): {stalled}")
    return {"checked": len(results), "alive": alive, "stalled": stalled}


def whitelist_step(*, log: Log = print) -> dict[str, object]:
    from .whitelist import load_index, refresh_lists

    status = refresh_lists()
    index = load_index()
    log(f"Белые списки: {status}, подсетей {len(index.starts)}, доменов {len(index.domains)}")
    return {"status": status, "ranges": len(index.starts), "domains": len(index.domains)}


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


def export_step(
    database: Path,
    output: Path,
    *,
    profiles: Path | None = DEFAULT_PROFILES_PATH,
    log: Log = print,
) -> dict[str, object]:
    store = NodeStore(database)
    try:
        records = store.list_ranked()
        export_ranked_catalog(records, output)
        export_sources(store.list_source_status(), output / "sources.json")
        index = export_smart_catalog(
            store, output / "smart", load_profiles(profiles), groups=groups_enabled(profiles)
        )
    finally:
        store.close()
    alive = sum(item.alive is True for item in records)
    log(f"Экспортировано серверов: {len(records)}; живых: {alive} -> {output}")
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


def probes_sync_step(
    database: Path, identity: ProbeIdentity, repo: str, *, log: Log = print
) -> dict[str, object]:
    store = NodeStore(database)
    try:
        result = sync_probes(store, identity, repo)
    finally:
        store.close()
    imported = result["imported"]
    log(
        "Пробники: "
        + (", ".join(f"{name} ({count})" for name, count in imported.items()) or "чужих отчётов нет")  # type: ignore[union-attr]
    )
    for name, reason in result["skipped"].items():  # type: ignore[union-attr]
        log(f"  отчёт {name} пропущен: {reason}")
    return result


def probe_publish_step(
    database: Path, identity: ProbeIdentity, repo: str, *, log: Log = print
) -> dict[str, object]:
    store = NodeStore(database)
    try:
        store.register_probe(
            identity.probe_id, identity.region, kind=identity.kind, version=__version__
        )
        result = publish_report(store, identity, repo)
    finally:
        store.close()
    log(f"Отчёт пробника {identity.probe_id} ({identity.region}) опубликован: {result['results']} серверов")
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
    identity: ProbeIdentity | None = None
    try:
        identity = await asyncio.to_thread(
            load_identity,
            options.probe_identity_file,
            probe_id=options.probe_id,
            region=options.probe_region,
            kind=default_kind(),
        )
        report.steps["probe"] = {"probe_id": identity.probe_id, "region": identity.region}
    except Exception as exc:
        log(f"Идентичность пробника не определена: {exc}")
    probe_repo = options.resolve_probe_repo()

    if options.install_mihomo and not Path(options.binary).exists():
        await step("setup_mihomo", lambda: _install(options.binary, log))
    await step(
        "validate",
        lambda: validate_step(
            options.database,
            binary=options.binary,
            test_url=options.test_url,
            timeout_ms=options.timeout_ms,
            download_bytes=options.download_bytes,
            concurrency=options.validation_concurrency,
            geo_limit=options.geo_limit,
            limit=options.limit,
            recheck_minutes=options.recheck_minutes,
            probe=identity,
            log=log,
        ),
    )
    if options.probe_sync and identity is not None and probe_repo:
        await step(
            "probes",
            lambda: probes_sync_step(options.database, identity, probe_repo, log=log),
            blocking=True,
        )
    if options.whitelist:
        await step("whitelist", lambda: whitelist_step(log=log), blocking=True)
    if options.cleanup:
        await step(
            "cleanup",
            lambda: cleanup_step(options.database, unseen_days=options.unseen_days, log=log),
            blocking=True,
        )
    await step(
        "export",
        lambda: export_step(
            options.database, options.output, profiles=options.profiles, log=log
        ),
        blocking=True,
    )
    if options.publish is not None:
        target = options.publish
        await step(
            "publish",
            lambda: publish_step(options.database, target, log=log),
            blocking=True,
        )

    if options.probe_publish and identity is not None and probe_repo:
        await step(
            "probe_publish",
            lambda: probe_publish_step(options.database, identity, probe_repo, log=log),
            blocking=True,
        )

    report.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    report.duration_s = round(time.monotonic() - started, 1)
    return report
