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
    probe_id TEXT NOT NULL DEFAULT 'local',
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


RECENT_WINDOW = 10
HISTORY_KEEP = 50


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


SORT_COLUMNS = {
    "score": "alive DESC, quality_score DESC, stability_score DESC, latency_ms ASC",
    "stability": "alive DESC, stability_score DESC, quality_score DESC",
    "latency": "latency_ms IS NULL, latency_ms ASC, quality_score DESC",
    "jitter": "jitter_ms IS NULL, jitter_ms ASC, quality_score DESC",
    "checked": "last_checked IS NULL, last_checked DESC",
    "seen": "last_seen DESC",
}


class NodeStore:
    def __init__(self, path: str | Path, *, init_schema: bool = True):
        """Open the database.

        ``init_schema=False`` skips schema creation and migrations; the API
        uses it for cheap per-request connections after a single startup init.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Each connection serves one caller at a time; the API may hop threads.
        self.connection = sqlite3.connect(
            self.path, timeout=10.0, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 10000")
        if not init_schema:
            return
        # WAL lets the API read while collect/validate write.
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self._migrate_nodes()
        self._migrate_health_checks()
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_quality ON nodes(quality_score DESC)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_stability ON nodes(stability_score DESC)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_health_probe ON health_checks(probe_id)"
        )
        self.connection.commit()

    def _migrate_health_checks(self) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(health_checks)"
            ).fetchall()
        }
        if "probe_id" not in columns:
            self.connection.execute(
                "ALTER TABLE health_checks ADD COLUMN probe_id TEXT NOT NULL DEFAULT 'local'"
            )

    def _migrate_nodes(self) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(nodes)").fetchall()
        }
        added = set()
        for name, ddl in MIGRATION_COLUMNS.items():
            if name not in columns:
                self.connection.execute(f"ALTER TABLE nodes ADD COLUMN {name} {ddl}")
                added.add(name)
        if "stability_score" in added:
            self._backfill_scores()

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
                fingerprint, alive, latency_ms, exit_ip, country, asn, error,
                probe_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.fingerprint,
                int(result.alive),
                result.latency_ms,
                result.exit_ip,
                result.country or None,
                result.asn or None,
                result.error,
                result.probe_id or "local",
            ),
        )
        # Cumulative counters live in nodes, so old health_checks can be pruned.
        self.connection.execute(
            """
            UPDATE nodes SET
                success_count = success_count + ?,
                failure_count = failure_count + ?
            WHERE fingerprint = ?
            """,
            (int(result.alive), int(not result.alive), result.fingerprint),
        )
        score, stable, jitter, recent_rate = self._compute_scores(
            result.fingerprint, result.latency_ms, result.alive
        )
        self.connection.execute(
            """
            UPDATE nodes SET
                alive=?, latency_ms=?, jitter_ms=?, recent_success_rate=?,
                stability_score=?, quality_score=?, last_checked=CURRENT_TIMESTAMP,
                exit_ip=COALESCE(?, exit_ip), country=COALESCE(?, country),
                asn=COALESCE(?, asn), validation_error=?
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
                result.country or None,
                result.asn or None,
                result.error,
                result.fingerprint,
            ),
        )
        self._prune_history(result.fingerprint)
        self.connection.commit()
        return score

    def _compute_scores(
        self,
        fingerprint: str,
        latency_ms: float | None,
        alive: bool | None,
    ) -> tuple[float, float, float | None, float]:
        counts = self.connection.execute(
            "SELECT success_count, failure_count FROM nodes WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        successes = int(counts["success_count"] or 0) if counts else 0
        failures = int(counts["failure_count"] or 0) if counts else 0
        recent = self.connection.execute(
            """
            SELECT alive, latency_ms FROM health_checks
            WHERE fingerprint = ? ORDER BY id DESC LIMIT ?
            """,
            (fingerprint, RECENT_WINDOW),
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
            attempts=successes + failures,
            successes=successes,
            failures=failures,
            latency_ms=latency_ms,
            jitter_ms=jitter,
            recent_success_rate=recent_rate,
        )
        return (
            quality_score(stats, alive=alive),
            stability_score(stats),
            jitter,
            recent_rate,
        )

    def _prune_history(self, fingerprint: str) -> None:
        self.connection.execute(
            """
            DELETE FROM health_checks
            WHERE fingerprint = ? AND id NOT IN (
                SELECT id FROM health_checks WHERE fingerprint = ?
                ORDER BY id DESC LIMIT ?
            )
            """,
            (fingerprint, fingerprint, HISTORY_KEEP),
        )

    def prune_history(self) -> int:
        """Trim health_checks for every node to the last HISTORY_KEEP rows."""
        cursor = self.connection.execute(
            """
            DELETE FROM health_checks WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY fingerprint ORDER BY id DESC
                    ) AS rn
                    FROM health_checks
                ) WHERE rn > ?
            )
            """,
            (HISTORY_KEEP,),
        )
        self.connection.commit()
        return cursor.rowcount

    def _backfill_scores(self) -> None:
        """Recompute derived scores for nodes validated before a schema upgrade."""
        rows = self.connection.execute(
            """
            SELECT fingerprint, latency_ms, alive FROM nodes
            WHERE last_checked IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            alive = None if row["alive"] is None else bool(row["alive"])
            score, stable, jitter, recent_rate = self._compute_scores(
                row["fingerprint"], row["latency_ms"], alive
            )
            self.connection.execute(
                """
                UPDATE nodes SET jitter_ms=?, recent_success_rate=?,
                    stability_score=?, quality_score=?
                WHERE fingerprint=?
                """,
                (jitter, recent_rate, stable, score, row["fingerprint"]),
            )

    @staticmethod
    def _ranked_filters(
        *,
        alive_only: bool = False,
        min_score: float = 0.0,
        min_stability: float = 0.0,
        max_latency: float | None = None,
        country: str | None = None,
        protocol: str | None = None,
        checked_within_hours: int | None = None,
        seen_within_hours: int | None = None,
    ) -> tuple[str, list[object]]:
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
        return " AND ".join(where), params

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
        offset: int = 0,
        sort: str = "score",
    ) -> list[RankedNode]:
        if sort not in SORT_COLUMNS:
            raise ValueError(f"Неизвестная сортировка: {sort}")
        where, params = self._ranked_filters(
            alive_only=alive_only,
            min_score=min_score,
            min_stability=min_stability,
            max_latency=max_latency,
            country=country,
            protocol=protocol,
            checked_within_hours=checked_within_hours,
            seen_within_hours=seen_within_hours,
        )
        sql = f"SELECT * FROM nodes WHERE {where} ORDER BY {SORT_COLUMNS[sort]}"
        if limit is not None or offset:
            sql += " LIMIT ? OFFSET ?"
            params.extend([-1 if limit is None else int(limit), max(0, int(offset))])
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_ranked(row) for row in rows]

    def count_ranked(self, **filters: object) -> int:
        where, params = self._ranked_filters(**filters)  # type: ignore[arg-type]
        row = self.connection.execute(
            f"SELECT COUNT(*) AS n FROM nodes WHERE {where}", params
        ).fetchone()
        return int(row["n"])

    def get_ranked(self, fingerprint: str) -> RankedNode | None:
        row = self.connection.execute(
            "SELECT * FROM nodes WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return None if row is None else self._row_to_ranked(row)

    def node_history(self, fingerprint: str, limit: int = 50) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT checked_at, alive, latency_ms, exit_ip, country, asn, error, probe_id
            FROM health_checks WHERE fingerprint = ?
            ORDER BY id DESC LIMIT ?
            """,
            (fingerprint, max(1, int(limit))),
        ).fetchall()
        history = []
        for row in reversed(rows):
            item = dict(row)
            item["alive"] = bool(item["alive"])
            history.append(item)
        return history

    def stats(self) -> dict[str, object]:
        totals = self.connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN alive = 1 THEN 1 ELSE 0 END) AS alive,
                   SUM(CASE WHEN alive = 0 THEN 1 ELSE 0 END) AS dead,
                   SUM(CASE WHEN alive IS NULL THEN 1 ELSE 0 END) AS unchecked,
                   AVG(CASE WHEN alive = 1 THEN latency_ms END) AS avg_latency,
                   AVG(CASE WHEN alive = 1 THEN jitter_ms END) AS avg_jitter,
                   AVG(CASE WHEN alive = 1 THEN quality_score END) AS avg_score,
                   MAX(last_checked) AS last_checked,
                   MAX(last_seen) AS last_seen
            FROM nodes
            """
        ).fetchone()

        def grouped(column: str) -> dict[str, dict[str, int]]:
            rows = self.connection.execute(
                f"""
                SELECT {column} AS key, COUNT(*) AS total,
                       SUM(CASE WHEN alive = 1 THEN 1 ELSE 0 END) AS alive
                FROM nodes WHERE {column} IS NOT NULL AND {column} != ''
                GROUP BY {column} ORDER BY alive DESC, total DESC
                """
            ).fetchall()
            return {
                str(row["key"]): {"total": int(row["total"]), "alive": int(row["alive"] or 0)}
                for row in rows
            }

        def rounded(value: object) -> float | None:
            return None if value is None else round(float(value), 2)

        return {
            "total": int(totals["total"] or 0),
            "alive": int(totals["alive"] or 0),
            "dead": int(totals["dead"] or 0),
            "unchecked": int(totals["unchecked"] or 0),
            "average_latency_ms": rounded(totals["avg_latency"]),
            "average_jitter_ms": rounded(totals["avg_jitter"]),
            "average_score": rounded(totals["avg_score"]),
            "last_checked": totals["last_checked"],
            "last_seen": totals["last_seen"],
            "protocols": grouped("protocol"),
            "countries": grouped("UPPER(country)"),
        }

    def _row_to_ranked(self, row: sqlite3.Row) -> RankedNode:
        return RankedNode(
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
        seen_within_hours: int | None = 72,
        new_share: float = 0.5,
    ) -> list[ProxyNode]:
        """Pick nodes for validation without starving re-checks.

        Nodes that were never checked and nodes due for a re-check share the
        budget (``new_share`` of it goes to new nodes); any unused part of one
        half is given to the other. Nodes not seen in sources for
        ``seen_within_hours`` are skipped.
        """
        seen_clause = ""
        seen_params: list[object] = []
        if seen_within_hours is not None:
            seen_clause = " AND last_seen >= datetime('now', ?)"
            seen_params.append(f"-{max(0, int(seen_within_hours))} hours")

        def fetch_new(count: int | None) -> list[sqlite3.Row]:
            sql = (
                "SELECT * FROM nodes WHERE last_checked IS NULL"
                + seen_clause
                + " ORDER BY last_seen DESC, RANDOM()"
            )
            params = list(seen_params)
            if count is not None:
                sql += " LIMIT ?"
                params.append(count)
            return self.connection.execute(sql, params).fetchall()

        def fetch_due(count: int | None) -> list[sqlite3.Row]:
            # Previously alive nodes first, then the longest-unchecked ones.
            sql = (
                "SELECT * FROM nodes WHERE last_checked IS NOT NULL"
                " AND last_checked <= datetime('now', ?)"
                + seen_clause
                + " ORDER BY CASE WHEN alive = 1 THEN 0 ELSE 1 END,"
                " last_checked ASC, quality_score DESC"
            )
            params: list[object] = [
                f"-{max(0, int(recheck_after_minutes))} minutes",
                *seen_params,
            ]
            if count is not None:
                sql += " LIMIT ?"
                params.append(count)
            return self.connection.execute(sql, params).fetchall()

        if limit is None:
            rows = fetch_new(None) + fetch_due(None)
        else:
            limit = max(0, int(limit))
            share = min(1.0, max(0.0, new_share))
            new_quota = int(round(limit * share))
            due_quota = limit - new_quota
            new_rows = fetch_new(new_quota)
            due_rows = fetch_due(due_quota + (new_quota - len(new_rows)))
            spare = limit - len(new_rows) - len(due_rows)
            if spare > 0:
                new_rows = fetch_new(len(new_rows) + spare)
            rows = new_rows + due_rows
        return [self._row_to_node(row) for row in rows]

    def prune_sources(self, active_names: list[str]) -> int:
        """Drop stats of sources that were removed or disabled in the registry."""
        if not active_names:
            cursor = self.connection.execute("DELETE FROM sources")
        else:
            marks = ",".join("?" for _ in active_names)
            cursor = self.connection.execute(
                f"DELETE FROM sources WHERE name NOT IN ({marks})",
                list(active_names),
            )
        self.connection.commit()
        return cursor.rowcount
