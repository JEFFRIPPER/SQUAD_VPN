from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .collector import collect_sources, load_sources
from .exporter import export_catalog
from .parser import deduplicate, parse_subscription
from .store import NodeStore


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


def _export(args: argparse.Namespace) -> int:
    store = NodeStore(args.database)
    try:
        nodes = store.list_nodes()
    finally:
        store.close()
    export_catalog(nodes, args.output)
    print(f"Экспортировано узлов: {len(nodes)} -> {args.output}")
    return 0


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

    exp = sub.add_parser("export", help="Сгенерировать каталог подписок")
    exp.add_argument("--database", type=Path, default=DEFAULT_DB)
    exp.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "collect":
        return asyncio.run(_collect(args))
    if args.command == "import-file":
        return _import_file(args)
    if args.command == "export":
        return _export(args)
    parser.error("Неизвестная команда")
    return 2
