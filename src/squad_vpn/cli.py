from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .collector import collect_sources, load_sources
from .exporter import export_ranked_catalog
from .parser import deduplicate, parse_subscription
from .setup_mihomo import install_mihomo
from .store import NodeStore
from .validator import DEFAULT_BINARY, DEFAULT_TEST_URL, MihomoValidator


DEFAULT_DB = Path("data/squad_vpn.sqlite3")
DEFAULT_OUTPUT = Path("data/output")
DEFAULT_SOURCES = Path("config/sources.txt")


def _store_nodes(nodes, database: Path) -> int:
    store = NodeStore(database)
    try:
        return store.upsert_many(nodes)
    finally:
        store.close()


async def _collect(args: argparse.Namespace) -> int:
    urls = load_sources(args.sources)
    if not urls:
        print(f"Нет источников в {args.sources}")
        return 0
    nodes, errors = await collect_sources(urls, concurrency=args.concurrency)
    saved = _store_nodes(nodes, args.database)
    print(f"Собрано уникальных узлов: {len(nodes)}")
    print(f"Записано в базу: {saved}")
    if errors:
        print(f"Ошибок источников: {len(errors)}")
        for url, error in errors.items():
            print(f"  - {url}: {error}")
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
    store = NodeStore(args.database)
    try:
        nodes = store.list_nodes()
        if args.limit:
            nodes = nodes[: args.limit]
        if not nodes:
            print("В базе нет узлов для проверки")
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
        print(f"Проверено через Mihomo: {len(results)}")
        print(f"Живых: {alive}; мёртвых: {len(results) - alive}")
        if len(results) < len(nodes):
            print(f"Не удалось конвертировать в Mihomo: {len(nodes) - len(results)}")
    finally:
        store.close()
    return 0


def _export(args: argparse.Namespace) -> int:
    store = NodeStore(args.database)
    try:
        records = store.list_ranked(
            alive_only=args.alive_only,
            min_score=args.min_score,
            limit=args.limit,
        )
    finally:
        store.close()
    export_ranked_catalog(records, args.output)
    alive = sum(item.alive is True for item in records)
    print(f"Экспортировано узлов: {len(records)}; живых: {alive} -> {args.output}")
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
    )
    await _validate(validate_args)
    export_args = argparse.Namespace(
        database=args.database,
        output=args.output,
        alive_only=False,
        min_score=0.0,
        limit=None,
    )
    return _export(export_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="squad-vpn")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="Собрать конфиги из URL-источников")
    collect.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    collect.add_argument("--database", type=Path, default=DEFAULT_DB)
    collect.add_argument("--concurrency", type=int, default=12)

    imp = sub.add_parser("import-file", help="Импортировать локальную подписку")
    imp.add_argument("path", type=Path)
    imp.add_argument("--database", type=Path, default=DEFAULT_DB)

    setup = sub.add_parser("setup-mihomo", help="Скачать официальный Mihomo для Windows x64")
    setup.add_argument("--target", type=Path, default=DEFAULT_BINARY)

    validate = sub.add_parser("validate", help="Проверить узлы через Mihomo")
    validate.add_argument("--database", type=Path, default=DEFAULT_DB)
    validate.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    validate.add_argument("--test-url", default=DEFAULT_TEST_URL)
    validate.add_argument("--timeout-ms", type=int, default=5000)
    validate.add_argument("--concurrency", type=int, default=16)
    validate.add_argument("--geo-limit", type=int, default=10)
    validate.add_argument("--limit", type=int)

    exp = sub.add_parser("export", help="Сгенерировать каталог и лучшие подписки")
    exp.add_argument("--database", type=Path, default=DEFAULT_DB)
    exp.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    exp.add_argument("--alive-only", action="store_true")
    exp.add_argument("--min-score", type=float, default=0.0)
    exp.add_argument("--limit", type=int)

    run = sub.add_parser("run", help="Collect -> validate -> export")
    run.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    run.add_argument("--database", type=Path, default=DEFAULT_DB)
    run.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    run.add_argument("--test-url", default=DEFAULT_TEST_URL)
    run.add_argument("--timeout-ms", type=int, default=5000)
    run.add_argument("--source-concurrency", type=int, default=12)
    run.add_argument("--validation-concurrency", type=int, default=16)
    run.add_argument("--geo-limit", type=int, default=10)
    run.add_argument("--limit", type=int)
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
    if args.command == "export":
        return _export(args)
    if args.command == "run":
        return asyncio.run(_run(args))
    parser.error("Неизвестная команда")
    return 2
