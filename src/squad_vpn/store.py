from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import ProxyNode


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    fingerprint TEXT PRIMARY KEY,
    protocol TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    userinfo TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    name TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    raw_uri TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_nodes_protocol ON nodes(protocol);
CREATE INDEX IF NOT EXISTS idx_nodes_host ON nodes(host);
"""


class NodeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def upsert_many(self, nodes: list[ProxyNode]) -> int:
        sql = """
        INSERT INTO nodes (
            fingerprint, protocol, host, port, userinfo,
            params_json, name, source, raw_uri
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fingerprint) DO UPDATE SET
            protocol=excluded.protocol,
            host=excluded.host,
            port=excluded.port,
            userinfo=excluded.userinfo,
            params_json=excluded.params_json,
            name=excluded.name,
            source=excluded.source,
            raw_uri=excluded.raw_uri,
            last_seen=CURRENT_TIMESTAMP
        """
        rows = [
            (
                node.fingerprint,
                node.protocol,
                node.host,
                node.port,
                node.userinfo,
                json.dumps(node.params, ensure_ascii=False, sort_keys=True),
                node.name,
                node.source,
                node.raw_uri,
            )
            for node in nodes
        ]
        self.connection.executemany(sql, rows)
        self.connection.commit()
        return len(rows)

    def list_nodes(self) -> list[ProxyNode]:
        rows = self.connection.execute(
            "SELECT protocol, host, port, userinfo, params_json, name, source, raw_uri "
            "FROM nodes ORDER BY protocol, host, port"
        ).fetchall()
        return [
            ProxyNode(
                protocol=row["protocol"],
                host=row["host"],
                port=row["port"],
                userinfo=row["userinfo"],
                params=json.loads(row["params_json"]),
                name=row["name"],
                source=row["source"],
                raw_uri=row["raw_uri"],
            )
            for row in rows
        ]

    def count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()
        return int(row["n"])
