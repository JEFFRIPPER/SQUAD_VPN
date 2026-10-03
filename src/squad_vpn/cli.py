from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
from pathlib import Path

from .cycle import (
    CycleOptions,
    cleanup_step,
    collect_step,
    publish_step,
    run_cycle,
    validate_step,
)
from .exporter import export_ranked_catalog, export_sources
from .parser import deduplicate, parse_subscription
from .publish import PublishError, PublishTarget, detect_origin
from .setup_mihomo import install_mihomo
from .smart import (
    DEFAULT_PROFILES_PATH,
    export_custom_subscription,
    export_smart_catalog,
    load_profiles,
)
from .store import NodeStore
from .validator import DEFAULT_BINARY, DEFAULT_TEST_URL


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
    await collect_step(args.sources, args.database, concurrency=args.concurrency)
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
    try:
        await validate_step(
            args.database,
            binary=args.binary,
            test_url=args.test_url,
            timeout_ms=args.timeout_ms,
            concurrency=args.concurrency,
            geo_limit=args.geo_limit,
            limit=args.limit,
            recheck_minutes=args.recheck_minutes,
        )
    except FileNotFoundError as exc:
        print(exc)
        return 1
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
            export_smart_catalog(store, args.output / "smart", load_profiles(args.profiles))
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


def _publish_target(args: argparse.Namespace) -> PublishTarget | None:
    if not getattr(args, "publish", False):
        return None
    repo = args.publish_repo or os.environ.get("SQUAD_PUBLISH_REPO") or detect_origin()
    if not repo:
        raise SystemExit(
            "Не удалось определить репозиторий для публикации: укажи --publish-repo"
        )
    return PublishTarget(
        repo=repo,
        branch=args.publish_branch,
        workdir=args.publish_workdir,
        profiles=args.profiles,
    )


def _cycle_options(args: argparse.Namespace) -> CycleOptions:
    return CycleOptions(
        sources=args.sources,
        database=args.database,
        output=args.output,
        source_concurrency=args.source_concurrency,
        binary=args.binary,
        test_url=args.test_url,
        timeout_ms=args.timeout_ms,
        validation_concurrency=args.validation_concurrency,
        geo_limit=args.geo_limit,
        limit=args.limit,
        recheck_minutes=args.recheck_minutes,
        cleanup=not args.no_cleanup,
        unseen_days=args.unseen_days,
        publish=_publish_target(args),
        profiles=args.profiles,
    )


async def _run(args: argparse.Namespace) -> int:
    report = await run_cycle(_cycle_options(args))
    print(f"Цикл завершён за {report.duration_s} с" + ("" if report.ok else " с ошибками"))
    for error in report.errors:
        print(f"  ! {error}")
    if args.strict and not report.ok:
        return 1
    return 0


def _cleanup(args: argparse.Namespace) -> int:
    cleanup_step(args.database, unseen_days=args.unseen_days)
    return 0


def _publish(args: argparse.Namespace) -> int:
    args.publish = True
    target = _publish_target(args)
    assert target is not None
    try:
        result = publish_step(args.database, target)
    except PublishError as exc:
        print(f"Публикация не удалась: {exc}")
        return 1
    for name, count in result["profiles"].items():  # type: ignore[union-attr]
        print(f"  {name}: {count} узлов -> {result['raw_base']}{name}.b64")
    return 0


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


def _agent(args: argparse.Namespace) -> int:
    from .agent import Agent, project_root, request_stop, setup_logging

    if args.stop:
        if request_stop():
            print("Агент остановлен")
            return 0
        print("Агент не запущен")
        return 1
    root = project_root()
    os.chdir(root)
    setup_logging(root)
    return Agent(
        root,
        port=args.port,
        interval_minutes=args.interval_minutes,
        update_hours=args.update_hours,
        auto_update=not args.no_update,
    ).run()


def _autostart(args: argparse.Namespace) -> int:
    from . import autostart
    from .agent import project_root

    try:
        if args.disable:
            for path in autostart.disable():
                print(f"Удалено: {path}")
            return 0
        for path in autostart.enable(project_root(), port=args.port):
            print(f"Создано: {path}")
    except OSError as exc:
        print(f"Не удалось настроить автозапуск: {exc}")
        return 1
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
    cycle = _cycle_options(args) if args.watch else None
    if cycle is not None:
        print(f"Фоновый цикл: каждые {args.interval_minutes} мин.")
    serve(
        args.database,
        host=args.host,
        port=args.port,
        token=token,
        cycle=cycle,
        interval_minutes=args.interval_minutes,
        profiles_path=args.profiles,
    )
    return 0


def _add_validation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--test-url", default=DEFAULT_TEST_URL)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--validation-concurrency", type=int, default=16)
    parser.add_argument("--geo-limit", type=int, default=10)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--recheck-minutes", type=int, default=60)


def _add_publish_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--publish-repo",
        help="git-репозиторий для публикации (по умолчанию origin этого проекта "
        "или SQUAD_PUBLISH_REPO)",
    )
    parser.add_argument(
        "--publish-branch",
        default="subs-home",
        help="Ветка для подписок (по умолчанию subs-home; GitHub Actions пишет в subs)",
    )
    parser.add_argument("--publish-workdir", type=Path, default=Path("data/publish"))
    _add_profiles_arg(parser)


def _add_profiles_arg(parser: argparse.ArgumentParser) -> None:
    if any("--profiles" in action.option_strings for action in parser._actions):
        return
    parser.add_argument(
        "--profiles",
        type=Path,
        default=DEFAULT_PROFILES_PATH,
        help="YAML со smart-профилями (по умолчанию config/profiles.yaml)",
    )


def _add_cycle_args(parser: argparse.ArgumentParser, *, with_database: bool = True) -> None:
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    if with_database:
        parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-concurrency", type=int, default=12)
    _add_validation_args(parser)
    parser.add_argument("--no-cleanup", action="store_true", help="Не удалять старые узлы")
    parser.add_argument("--unseen-days", type=int, default=3)
    parser.add_argument(
        "--publish", action="store_true", help="Публиковать подписки в git-ветку"
    )
    _add_publish_args(parser)


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
    _add_profiles_arg(exp)

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

    run = sub.add_parser(
        "run", help="Collect -> validate -> cleanup -> export (-> publish)"
    )
    _add_cycle_args(run)
    run.add_argument(
        "--strict", action="store_true", help="Код выхода 1, если какой-то шаг упал"
    )

    watch = sub.add_parser("watch", help="Периодически выполнять полный цикл")
    _add_cycle_args(watch)
    watch.add_argument("--interval-minutes", type=int, default=60)
    watch.add_argument("--cycles", type=int, default=0, help="0 = бесконечно")
    watch.add_argument("--stop-on-error", action="store_true")
    watch.add_argument("--strict", action="store_true", help=argparse.SUPPRESS)

    clean = sub.add_parser("cleanup", help="Удалить узлы, пропавшие из источников")
    clean.add_argument("--database", type=Path, default=DEFAULT_DB)
    clean.add_argument("--unseen-days", type=int, default=3)

    pub = sub.add_parser("publish", help="Опубликовать подписки в git-ветку")
    pub.add_argument("--database", type=Path, default=DEFAULT_DB)
    _add_publish_args(pub)

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
    srv.add_argument(
        "--watch",
        action="store_true",
        help="Фоново выполнять полный цикл каждые --interval-minutes",
    )
    srv.add_argument("--interval-minutes", type=int, default=60)
    _add_cycle_args(srv, with_database=False)

    agent = sub.add_parser(
        "agent",
        help="Фоновый агент: панель, ежечасный цикл, перезапуск и автообновление",
    )
    agent.add_argument("--port", type=int, default=8080)
    agent.add_argument("--interval-minutes", type=int, default=60)
    agent.add_argument(
        "--update-hours", type=float, default=3.0, help="Как часто проверять обновления"
    )
    agent.add_argument("--no-update", action="store_true", help="Не обновлять код сам")
    agent.add_argument("--stop", action="store_true", help="Остановить запущенного агента")

    auto = sub.add_parser("autostart", help="Автозапуск агента при входе в Windows")
    auto.add_argument("--disable", action="store_true", help="Убрать автозапуск и ярлык")
    auto.add_argument("--port", type=int, default=8080)
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
    if args.command == "autostart":
        return _autostart(args)
    if args.command == "agent":
        return _agent(args)
    if args.command == "cleanup":
        return _cleanup(args)
    if args.command == "publish":
        return _publish(args)
    parser.error("Неизвестная команда")
    return 2
