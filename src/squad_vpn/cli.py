from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
from pathlib import Path

from .collector import collect_source_specs
from .exporter import export_ranked_catalog, export_sources
from .parser import deduplicate, parse_subscription
from .setup_mihomo import install_mihomo
from .smart import export_custom_subscription, export_smart_catalog
from .sources import load_source_specs
from .store import NodeStore
from .validator import DEFAULT_BINARY, DEFAULT_TEST_URL, MihomoValidator


DEFAULT_DB = Path("data/squad_vpn.sqlite3")
DEFAULT_OUTPUT = Path("data/output")
DEFAULT_SOURCES = Path("config/sources.yaml")


def _store_nodes(nodes, database: Path) -> int:
    store = NodeStore(database)
    try:
        return store.upsert_many(nodes)
    finally:
        store.close()


async def _collect(args: argparse.Namespace) -> int:
    specs = load_source_specs(args.sources)
    if not specs:
        print(f"Нет включённых источников в {args.sources}")
        return 0
    nodes, reports = await collect_source_specs(
        specs, concurrency=args.concurrency
    )
    store = NodeStore(args.database)
    try:
        saved = store.upsert_many(nodes)
        for report in reports:
            store.record_source_report(report)
        store.prune_sources([spec.name for spec in specs])
    finally:
        store.close()

    ok = sum(report.ok for report in reports)
    failed = len(reports) - ok
    print(f"Источников: {len(reports)}; успешно: {ok}; ошибок: {failed}")
    print(f"Собрано уникальных узлов: {len(nodes)}")
    print(f"Записано в базу: {saved}")
    for report in reports:
        state = "OK" if report.ok else "ERR"
        print(
            f"  [{state}] {report.source.name}: "
            f"{report.nodes_selected}/{report.nodes_found} узлов, "
            f"{report.duration_ms:.0f} ms"
        )
        if report.error:
            print(f"       {report.error}")
    return 0


def _import_file(args: argparse.Namespace) -> int:
    text = args.path.read_text(encoding="utf-8-sig")
    nodes = deduplicate(parse_subscription(text, source=str(args.path)))
    saved = _store_nodes(nodes, args.database)
    print(f"Импортировано уникальных узлов: {saved}")
    return 0


async def _setup_mihomo(args: argparse.Namespace) -> int:
    target, version = await install_mihomo(args.target)
    print(f"Mihomo {version} установлен: {target}")
    return 0


async def _validate(args: argparse.Namespace) -> int:
    if not Path(args.binary).exists():
        print(f"Mihomo не найден: {args.binary}. Выполни squad-vpn setup-mihomo")
        return 1
    store = NodeStore(args.database)
    try:
        nodes = store.list_validation_candidates(
            recheck_after_minutes=args.recheck_minutes,
            limit=args.limit,
        )
        if not nodes:
            print("Нет узлов, которым сейчас нужна проверка")
            return 0
        validator = MihomoValidator(
            args.binary,
            test_url=args.test_url,
            timeout_ms=args.timeout_ms,
        )
        results = await validator.validate(
            nodes,
            concurrency=args.concurrency,
            geo_limit=args.geo_limit,
        )
        alive = 0
        for result in results:
            store.record_validation(result)
            alive += int(result.alive)
        store.prune_history()
        print(f"Проверено через Mihomo: {len(results)}")
        print(f"Живых: {alive}; мёртвых: {len(results) - alive}")
    finally:
        store.close()
    return 0


def _export(args: argparse.Namespace) -> int:
    store = NodeStore(args.database)
    try:
        records = store.list_ranked(
            alive_only=args.alive_only,
            min_score=args.min_score,
            min_stability=args.min_stability,
            max_latency=args.max_latency,
            country=args.country,
            protocol=args.protocol,
            checked_within_hours=args.checked_within_hours,
            seen_within_hours=args.seen_within_hours,
            limit=args.limit,
        )
        export_ranked_catalog(records, args.output)
        export_sources(store.list_source_status(), args.output / "sources.json")
        if not args.no_smart:
            export_smart_catalog(store, args.output / "smart")
    finally:
        store.close()
    alive = sum(item.alive is True for item in records)
    print(f"Экспортировано узлов: {len(records)}; живых: {alive} -> {args.output}")
    return 0


def _smart(args: argparse.Namespace) -> int:
    store = NodeStore(args.database)
    try:
        records = export_custom_subscription(
            store,
            args.output,
            min_score=args.min_score,
            min_stability=args.min_stability,
            max_latency=args.max_latency,
            country=args.country,
            protocol=args.protocol,
            checked_within_hours=args.checked_within_hours,
            seen_within_hours=args.seen_within_hours,
            limit=args.limit,
        )
    finally:
        store.close()
    print(f"Smart-подписка: {len(records)} узлов -> {args.output}")
    return 0


def _sources_status(args: argparse.Namespace) -> int:
    store = NodeStore(args.database)
    try:
        rows = store.list_source_status()
    finally:
        store.close()
    if not rows:
        print("Статистика источников пока пуста")
        return 0
    for row in rows:
        total = int(row["fetch_count"] or 0)
        ok = int(row["success_count"] or 0)
        print(
            f"{row['name']}: {ok}/{total} OK, "
            f"nodes={row['nodes_selected']}, {row['duration_ms'] or 0:.0f} ms"
        )
        if row.get("last_error"):
            print(f"  last_error: {row['last_error']}")
    return 0


async def _run(args: argparse.Namespace) -> int:
    collect_args = argparse.Namespace(
        sources=args.sources,
        database=args.database,
        concurrency=args.source_concurrency,
    )
    await _collect(collect_args)
    validate_args = argparse.Namespace(
        database=args.database,
        binary=args.binary,
        test_url=args.test_url,
        timeout_ms=args.timeout_ms,
        concurrency=args.validation_concurrency,
        geo_limit=args.geo_limit,
        limit=args.limit,
        recheck_minutes=args.recheck_minutes,
    )
    try:
        await _validate(validate_args)
    except (FileNotFoundError, RuntimeError, TimeoutError) as exc:
        # Export still runs so subscriptions are refreshed from existing data.
        print(f"Проверка пропущена: {exc}")
    export_args = argparse.Namespace(
        database=args.database,
        output=args.output,
        alive_only=False,
        min_score=0.0,
        min_stability=0.0,
        max_latency=None,
        country=None,
        protocol=None,
        checked_within_hours=None,
        seen_within_hours=None,
        limit=None,
        no_smart=False,
    )
    return _export(export_args)


async def _watch(args: argparse.Namespace) -> int:
    cycle = 0
    while args.cycles == 0 or cycle < args.cycles:
        cycle += 1
        print(f"=== SQUAD VPN cycle {cycle} ===")
        try:
            await _run(args)
        except Exception as exc:
            print(f"Цикл завершился ошибкой: {exc}")
            if args.stop_on_error:
                raise
        if args.cycles and cycle >= args.cycles:
            break
        delay = max(1, args.interval_minutes) * 60
        print(f"Следующий цикл через {args.interval_minutes} мин.")
        await asyncio.sleep(delay)
    return 0


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _serve(args: argparse.Namespace) -> int:
    from .api import serve

    token = args.token or os.environ.get("SQUAD_VPN_TOKEN") or None
    if not _is_loopback(args.host) and not token and not args.insecure_no_token:
        print(
            f"Отказ: {args.host} доступен из сети, а token не задан. "
            "Укажи --token (или SQUAD_VPN_TOKEN), либо --insecure-no-token."
        )
        return 2
    url = f"http://{args.host}:{args.port}/"
    print(f"SQUAD VPN API: {url}" + (f"?token={token}" if token else ""))
    serve(args.database, host=args.host, port=args.port, token=token)
    return 0


def _add_validation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--test-url", default=DEFAULT_TEST_URL)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--validation-concurrency", type=int, default=16)
    parser.add_argument("--geo-limit", type=int, default=10)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--recheck-minutes", type=int, default=60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="squad-vpn")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="Собрать конфиги из реестра источников")
    collect.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    collect.add_argument("--database", type=Path, default=DEFAULT_DB)
    collect.add_argument("--concurrency", type=int, default=12)

    imp = sub.add_parser("import-file", help="Импортировать локальную подписку")
    imp.add_argument("path", type=Path)
    imp.add_argument("--database", type=Path, default=DEFAULT_DB)

    setup = sub.add_parser("setup-mihomo", help="Скачать официальный Mihomo")
    setup.add_argument("--target", type=Path, default=DEFAULT_BINARY)

    validate = sub.add_parser("validate", help="Проверить просроченные узлы через Mihomo")
    validate.add_argument("--database", type=Path, default=DEFAULT_DB)
    validate.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    validate.add_argument("--test-url", default=DEFAULT_TEST_URL)
    validate.add_argument("--timeout-ms", type=int, default=5000)
    validate.add_argument("--concurrency", type=int, default=16)
    validate.add_argument("--geo-limit", type=int, default=10)
    validate.add_argument("--limit", type=int, default=200)
    validate.add_argument("--recheck-minutes", type=int, default=60)

    sources = sub.add_parser("sources", help="Показать здоровье источников")
    sources.add_argument("--database", type=Path, default=DEFAULT_DB)

    exp = sub.add_parser("export", help="Сгенерировать каталог и smart-подписки")
    exp.add_argument("--database", type=Path, default=DEFAULT_DB)
    exp.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    exp.add_argument("--alive-only", action="store_true")
    exp.add_argument("--min-score", type=float, default=0.0)
    exp.add_argument("--min-stability", type=float, default=0.0)
    exp.add_argument("--max-latency", type=float)
    exp.add_argument("--country")
    exp.add_argument("--protocol")
    exp.add_argument("--checked-within-hours", type=int)
    exp.add_argument("--seen-within-hours", type=int)
    exp.add_argument("--limit", type=int)
    exp.add_argument("--no-smart", action="store_true")

    smart = sub.add_parser("smart", help="Создать одну подписку по фильтрам")
    smart.add_argument("--database", type=Path, default=DEFAULT_DB)
    smart.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "smart" / "custom")
    smart.add_argument("--min-score", type=float, default=0.0)
    smart.add_argument("--min-stability", type=float, default=0.0)
    smart.add_argument("--max-latency", type=float)
    smart.add_argument("--country")
    smart.add_argument("--protocol")
    smart.add_argument("--checked-within-hours", type=int, default=12)
    smart.add_argument("--seen-within-hours", type=int, default=48)
    smart.add_argument("--limit", type=int, default=300)

    run = sub.add_parser("run", help="Collect -> validate -> export -> smart")
    run.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    run.add_argument("--database", type=Path, default=DEFAULT_DB)
    run.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run.add_argument("--source-concurrency", type=int, default=12)
    _add_validation_args(run)

    watch = sub.add_parser("watch", help="Периодически выполнять полный цикл")
    watch.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    watch.add_argument("--database", type=Path, default=DEFAULT_DB)
    watch.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    watch.add_argument("--source-concurrency", type=int, default=12)
    watch.add_argument("--interval-minutes", type=int, default=60)
    watch.add_argument("--cycles", type=int, default=0, help="0 = бесконечно")
    watch.add_argument("--stop-on-error", action="store_true")
    _add_validation_args(watch)

    srv = sub.add_parser("serve", help="HTTP API, динамические подписки и веб-панель")
    srv.add_argument("--database", type=Path, default=DEFAULT_DB)
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8080)
    srv.add_argument("--token", help="Токен доступа (или переменная SQUAD_VPN_TOKEN)")
    srv.add_argument(
        "--insecure-no-token",
        action="store_true",
        help="Разрешить сетевой доступ без токена",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "collect":
        return asyncio.run(_collect(args))
    if args.command == "import-file":
        return _import_file(args)
    if args.command == "setup-mihomo":
        return asyncio.run(_setup_mihomo(args))
    if args.command == "validate":
        return asyncio.run(_validate(args))
    if args.command == "sources":
        return _sources_status(args)
    if args.command == "export":
        return _export(args)
    if args.command == "smart":
        return _smart(args)
    if args.command == "run":
        return asyncio.run(_run(args))
    if args.command == "watch":
        return asyncio.run(_watch(args))
    if args.command == "serve":
        return _serve(args)
    parser.error("Неизвестная команда")
    return 2
