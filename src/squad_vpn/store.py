from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import pstdev

from .models import ProxyNode, RankedNode, ValidationResult
from .scoring import HealthStats, quality_score, stability_score
from .sources import SourceReport


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
    last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    alive INTEGER,
    latency_ms REAL,
    jitter_ms REAL,
    recent_success_rate REAL NOT NULL DEFAULT 0,
    stability_score REAL NOT NULL DEFAULT 0,
    quality_score REAL NOT NULL DEFAULT 0,
    last_checked TEXT,
    exit_ip TEXT,
    country TEXT,
    asn TEXT,
    validation_error TEXT,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nodes_protocol ON nodes(protocol);
CREATE INDEX IF NOT EXISTS idx_nodes_host ON nodes(host);

CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    alive INTEGER NOT NULL,
    latency_ms REAL,
    exit_ip TEXT,
    country TEXT,
    asn TEXT,
    error TEXT,
    FOREIGN KEY(fingerprint) REFERENCES nodes(fingerprint) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_health_fingerprint ON health_checks(fingerprint);
CREATE INDEX IF NOT EXISTS idx_health_checked_at ON health_checks(checked_at);

CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    priority INTEGER NOT NULL DEFAULT 100,
    fetch_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    nodes_found INTEGER NOT NULL DEFAULT 0,
    nodes_selected INTEGER NOT NULL DEFAULT 0,
    duration_ms REAL,
    last_fetch TEXT,
    last_ok TEXT,
    last_error TEXT
);
"""


MIGRATION_COLUMNS = {
    "alive": "INTEGER",
    "latency_ms": "REAL",
    "jitter_ms": "REAL",
    "recent_success_rate": "REAL NOT NULL DEFAULT 0",
    "stability_score": "REAL NOT NULL DEFAULT 0",
    "quality_score": "REAL NOT NULL DEFAULT 0",
    "last_checked": "TEXT",
    "exit_ip": "TEXT",
    "country": "TEXT",
    "asn": "TEXT",
    "validation_error": "TEXT",
    "success_count": "INTEGER NOT NULL DEFAULT 0",
    "failure_count": "INTEGER NOT NULL DEFAULT 0",
}


class NodeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        self._migrate_nodes()
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_quality ON nodes(quality_score DESC)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_stability ON nodes(stability_score DESC)"
        )
        self.connection.commit()

    def _migrate_nodes(self) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(nodes)").fetchall()
        }
        for name, ddl in MIGRATION_COLUMNS.items():
            if name not in columns:
                self.connection.execute(f"ALTER TABLE nodes ADD COLUMN {name} {ddl}")

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

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> ProxyNode:
        return ProxyNode(
            protocol=row["protocol"],
            host=row["host"],
            port=row["port"],
            userinfo=row["userinfo"],
            params=json.loads(row["params_json"]),
            name=row["name"],
            source=row["source"],
            raw_uri=row["raw_uri"],
        )

    def list_nodes(self) -> list[ProxyNode]:
        rows = self.connection.execute(
            "SELECT * FROM nodes ORDER BY protocol, host, port"
        ).fetchall()
        return [self._row_to_node(row) for row in rows]

    def record_source_report(self, report: SourceReport) -> None:
        spec = report.source
        self.connection.execute(
            """
            INSERT INTO sources (
                name, url, tags_json, priority, fetch_count, success_count,
                failure_count, nodes_found, nodes_selected, duration_ms,
                last_fetch, last_ok, last_error
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP,
                CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END, ?)
            ON CONFLICT(name) DO UPDATE SET
                url=excluded.url,
                tags_json=excluded.tags_json,
                priority=excluded.priority,
                fetch_count=sources.fetch_count + 1,
                success_count=sources.success_count + excluded.success_count,
                failure_count=sources.failure_count + excluded.failure_count,
                nodes_found=excluded.nodes_found,
                nodes_selected=excluded.nodes_selected,
                duration_ms=excluded.duration_ms,
                last_fetch=CURRENT_TIMESTAMP,
                last_ok=CASE WHEN excluded.success_count = 1
                    THEN CURRENT_TIMESTAMP ELSE sources.last_ok END,
                last_error=excluded.last_error
            """,
            (
                spec.name,
                spec.url,
                json.dumps(spec.tags, ensure_ascii=False),
                spec.priority,
                int(report.ok),
                int(not report.ok),
                report.nodes_found,
                report.nodes_selected,
                report.duration_ms,
                int(report.ok),
                report.error,
            ),
        )
        self.connection.commit()

    def record_validation(self, result: ValidationResult) -> float:
        self.connection.execute(
            """
            INSERT INTO health_checks (
                fingerprint, alive, latency_ms, exit_ip, country, asn, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.fingerprint,
                int(result.alive),
                result.latency_ms,
                result.exit_ip,
                result.country,
                result.asn,
                result.error,
            ),
        )
        counts = self.connection.execute(
            """
            SELECT COUNT(*) AS attempts,
                   SUM(CASE WHEN alive = 1 THEN 1 ELSE 0 END) AS successes,
                   SUM(CASE WHEN alive = 0 THEN 1 ELSE 0 END) AS failures
            FROM health_checks WHERE fingerprint = ?
            """,
            (result.fingerprint,),
        ).fetchone()
        recent = self.connection.execute(
            """
            SELECT alive, latency_ms FROM health_checks
            WHERE fingerprint = ? ORDER BY id DESC LIMIT 10
            """,
            (result.fingerprint,),
        ).fetchall()
        recent_successes = sum(int(row["alive"]) for row in recent)
        recent_rate = recent_successes / len(recent) if recent else 0.0
        recent_latencies = [
            float(row["latency_ms"])
            for row in recent
            if row["alive"] and row["latency_ms"] is not None
        ]
        jitter = pstdev(recent_latencies) if len(recent_latencies) >= 2 else None
        stats = HealthStats(
            attempts=int(counts["attempts"] or 0),
            successes=int(counts["successes"] or 0),
            failures=int(counts["failures"] or 0),
            latency_ms=result.latency_ms,
            jitter_ms=jitter,
            recent_success_rate=recent_rate,
        )
        score = quality_score(stats, alive=result.alive)
        stable = stability_score(stats)
        self.connection.execute(
            """
            UPDATE nodes SET
                alive=?, latency_ms=?, jitter_ms=?, recent_success_rate=?,
                stability_score=?, quality_score=?, last_checked=CURRENT_TIMESTAMP,
                exit_ip=COALESCE(?, exit_ip), country=COALESCE(?, country),
                asn=COALESCE(?, asn), validation_error=?,
                success_count=?, failure_count=?
            WHERE fingerprint=?
            """,
            (
                int(result.alive),
                result.latency_ms,
                jitter,
                recent_rate,
                stable,
                score,
                result.exit_ip,
                result.country,
                result.asn,
                result.error,
                stats.successes,
                stats.failures,
                result.fingerprint,
            ),
        )
        self.connection.commit()
        return score

    def list_ranked(
        self,
        *,
        alive_only: bool = False,
        min_score: float = 0.0,
        min_stability: float = 0.0,
        max_latency: float | None = None,
        country: str | None = None,
        protocol: str | None = None,
        checked_within_hours: int | None = None,
        seen_within_hours: int | None = None,
        limit: int | None = None,
    ) -> list[RankedNode]:
        where = ["quality_score >= ?", "stability_score >= ?"]
        params: list[object] = [float(min_score), float(min_stability)]
        if alive_only:
            where.append("alive = 1")
        if max_latency is not None:
            where.append("latency_ms IS NOT NULL AND latency_ms <= ?")
            params.append(float(max_latency))
        if country:
            where.append("UPPER(country) = ?")
            params.append(country.upper())
        if protocol:
            where.append("LOWER(protocol) = ?")
            params.append(protocol.lower())
        if checked_within_hours is not None:
            where.append("last_checked >= datetime('now', ?)")
            params.append(f"-{int(checked_within_hours)} hours")
        if seen_within_hours is not None:
            where.append("last_seen >= datetime('now', ?)")
            params.append(f"-{int(seen_within_hours)} hours")

        sql = "SELECT * FROM nodes WHERE " + " AND ".join(where)
        sql += (
            " ORDER BY alive DESC, quality_score DESC, stability_score DESC, "
            "latency_ms ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self.connection.execute(sql, params).fetchall()
        result: list[RankedNode] = []
        for row in rows:
            result.append(
                RankedNode(
                    node=self._row_to_node(row),
                    alive=None if row["alive"] is None else bool(row["alive"]),
                    latency_ms=row["latency_ms"],
                    jitter_ms=row["jitter_ms"],
                    recent_success_rate=float(row["recent_success_rate"] or 0.0),
                    stability_score=float(row["stability_score"] or 0.0),
                    quality_score=float(row["quality_score"] or 0.0),
                    last_checked=row["last_checked"],
                    last_seen=row["last_seen"],
                    exit_ip=row["exit_ip"],
                    country=row["country"],
                    asn=row["asn"],
                    success_count=int(row["success_count"] or 0),
                    failure_count=int(row["failure_count"] or 0),
                    validation_error=row["validation_error"],
                )
            )
        return result

    def list_source_status(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            "SELECT * FROM sources ORDER BY priority, name"
        ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()
        return int(row["n"])

    def list_validation_candidates(
        self,
        *,
        recheck_after_minutes: int = 60,
        limit: int | None = None,
    ) -> list[ProxyNode]:
        sql = """
        SELECT * FROM nodes
        WHERE last_checked IS NULL
           OR last_checked <= datetime('now', ?)
        ORDER BY
            CASE WHEN last_checked IS NULL THEN 0 ELSE 1 END,
            CASE WHEN last_checked IS NULL
                THEN ABS(RANDOM()) ELSE unixepoch(last_checked) END ASC,
            quality_score DESC
        """
        params: list[object] = [f"-{max(0, int(recheck_after_minutes))} minutes"]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_node(row) for row in rows]
