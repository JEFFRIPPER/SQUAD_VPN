from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import pstdev

from .models import ProxyNode, RankedNode, ValidationResult
from .scoring import (
    HealthStats,
    quality_score,
    representative_latency,
    stability_score,
    weighted_success_rate,
)
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
    last_alive TEXT,
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

CREATE TABLE IF NOT EXISTS probes (
    probe_id TEXT PRIMARY KEY,
    region TEXT NOT NULL DEFAULT '??',
    kind TEXT NOT NULL DEFAULT 'local',
    version TEXT,
    last_report TEXT,
    nodes INTEGER NOT NULL DEFAULT 0,
    is_self INTEGER NOT NULL DEFAULT 0
);

-- Latest view of every node from every probe (own and imported).
CREATE TABLE IF NOT EXISTS node_probe_status (
    fingerprint TEXT NOT NULL,
    probe_id TEXT NOT NULL,
    alive INTEGER NOT NULL,
    latency_ms REAL,
    checked_at TEXT NOT NULL,
    success_rate REAL NOT NULL DEFAULT 0,
    checks INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    PRIMARY KEY (fingerprint, probe_id)
);
CREATE INDEX IF NOT EXISTS idx_nps_probe ON node_probe_status(probe_id, checked_at);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

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
# Bump when scoring changes: stored scores are recomputed on next open.
SCORING_VERSION = 2
HISTORY_KEEP = 50


MIGRATION_COLUMNS = {
    "alive": "INTEGER",
    "latency_ms": "REAL",
    "jitter_ms": "REAL",
    "recent_success_rate": "REAL NOT NULL DEFAULT 0",
    "stability_score": "REAL NOT NULL DEFAULT 0",
    "quality_score": "REAL NOT NULL DEFAULT 0",
    "last_checked": "TEXT",
    "last_alive": "TEXT",
    "remote_alive_at": "TEXT",
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
        self._migrate_scoring()
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

    def _migrate_scoring(self) -> None:
        row = self.connection.execute(
            "SELECT value FROM meta WHERE key = 'scoring_version'"
        ).fetchone()
        current = int(row["value"]) if row else 0
        if current >= SCORING_VERSION:
            return
        has_checks = self.connection.execute(
            "SELECT 1 FROM nodes WHERE last_checked IS NOT NULL LIMIT 1"
        ).fetchone()
        if has_checks:
            self._backfill_scores()
        self.connection.execute(
            "INSERT INTO meta (key, value) VALUES ('scoring_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCORING_VERSION),),
        )

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
        if "last_alive" in added:
            self.connection.execute(
                """
                UPDATE nodes SET last_alive = (
                    SELECT MAX(checked_at) FROM health_checks h
                    WHERE h.fingerprint = nodes.fingerprint AND h.alive = 1
                )
                """
            )
            self.connection.execute(
                "UPDATE nodes SET last_alive = last_checked "
                "WHERE last_alive IS NULL AND alive = 1"
            )

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
        score, stable, jitter, recent_rate, latency = self._compute_scores(
            result.fingerprint, result.latency_ms, result.alive
        )
        self.connection.execute(
            """
            UPDATE nodes SET
                alive=?, latency_ms=?, jitter_ms=?, recent_success_rate=?,
                stability_score=?, quality_score=?, last_checked=CURRENT_TIMESTAMP,
                last_alive=CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE last_alive END,
                exit_ip=COALESCE(?, exit_ip), country=COALESCE(?, country),
                asn=COALESCE(?, asn), validation_error=?
            WHERE fingerprint=?
            """,
            (
                int(result.alive),
                latency,
                jitter,
                recent_rate,
                stable,
                score,
                int(result.alive),
                result.exit_ip,
                result.country or None,
                result.asn or None,
                result.error,
                result.fingerprint,
            ),
        )
        self._record_probe_status(result)
        self._prune_history(result.fingerprint)
        self.connection.commit()
        return score

    def _record_probe_status(self, result: ValidationResult) -> None:
        # EWMA keeps a per-probe success rate without per-probe history.
        self.connection.execute(
            """
            INSERT INTO node_probe_status (
                fingerprint, probe_id, alive, latency_ms, checked_at,
                success_rate, checks, error
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, 1, ?)
            ON CONFLICT(fingerprint, probe_id) DO UPDATE SET
                alive = excluded.alive,
                latency_ms = excluded.latency_ms,
                checked_at = excluded.checked_at,
                success_rate = 0.65 * node_probe_status.success_rate
                    + 0.35 * excluded.success_rate,
                checks = node_probe_status.checks + 1,
                error = excluded.error
            """,
            (
                result.fingerprint,
                result.probe_id or "local",
                int(result.alive),
                result.latency_ms,
                float(result.alive),
                (result.error or "")[:200] or None,
            ),
        )

    # --- probes -----------------------------------------------------------

    def register_probe(
        self, probe_id: str, region: str, *, kind: str = "local", version: str | None = None
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO probes (probe_id, region, kind, version, is_self)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(probe_id) DO UPDATE SET
                region = excluded.region, kind = excluded.kind,
                version = excluded.version, is_self = 1
            """,
            (probe_id, region.upper(), kind, version),
        )
        self.connection.commit()

    def probe_report_rows(self, probe_id: str, *, hours: int = 24) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT fingerprint, alive, latency_ms, checked_at, success_rate, checks, error
            FROM node_probe_status
            WHERE probe_id = ? AND checked_at >= datetime('now', ?)
            ORDER BY checked_at DESC
            """,
            (probe_id, f"-{int(hours)} hours"),
        ).fetchall()
        return [
            {
                "fp": row["fingerprint"],
                "alive": bool(row["alive"]),
                "latency_ms": row["latency_ms"],
                "checked_at": row["checked_at"],
                "rate": round(float(row["success_rate"]), 3),
                "checks": int(row["checks"]),
                "error": row["error"],
            }
            for row in rows
        ]

    def import_probe_results(
        self,
        probe_id: str,
        region: str,
        results: list[dict[str, object]],
        *,
        kind: str = "remote",
        version: str | None = None,
        generated_at: str | None = None,
    ) -> int:
        """Merge another probe's report; only newer results for known nodes."""
        self.connection.execute(
            """
            INSERT INTO probes (probe_id, region, kind, version, last_report, nodes, is_self)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(probe_id) DO UPDATE SET
                region = excluded.region, kind = excluded.kind,
                version = excluded.version, last_report = excluded.last_report,
                nodes = excluded.nodes
            """,
            (probe_id, region.upper(), kind, version, generated_at, len(results)),
        )
        imported = 0
        for item in results:
            cursor = self.connection.execute(
                """
                INSERT INTO node_probe_status (
                    fingerprint, probe_id, alive, latency_ms, checked_at,
                    success_rate, checks, error
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (SELECT 1 FROM nodes WHERE fingerprint = ?)
                ON CONFLICT(fingerprint, probe_id) DO UPDATE SET
                    alive = excluded.alive, latency_ms = excluded.latency_ms,
                    checked_at = excluded.checked_at,
                    success_rate = excluded.success_rate,
                    checks = excluded.checks, error = excluded.error
                WHERE excluded.checked_at > node_probe_status.checked_at
                """,
                (
                    item["fp"], probe_id, int(bool(item["alive"])), item.get("latency_ms"),
                    item["checked_at"], float(item.get("rate") or 0.0),  # type: ignore[arg-type]
                    int(item.get("checks") or 0), item.get("error"),  # type: ignore[call-overload]
                    item["fp"],
                ),
            )
            imported += cursor.rowcount
        self.connection.execute(
            """
            UPDATE nodes SET remote_alive_at = (
                SELECT MAX(s.checked_at) FROM node_probe_status s
                JOIN probes p ON p.probe_id = s.probe_id
                WHERE s.fingerprint = nodes.fingerprint AND s.alive = 1 AND p.is_self = 0
            )
            """
        )
        self.connection.commit()
        return imported

    def list_probes(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT p.probe_id, p.region, p.kind, p.version, p.last_report, p.is_self,
                   COUNT(s.fingerprint) AS checked,
                   SUM(CASE WHEN s.alive = 1 THEN 1 ELSE 0 END) AS alive,
                   MAX(s.checked_at) AS last_check
            FROM probes p
            LEFT JOIN node_probe_status s
              ON s.probe_id = p.probe_id AND s.checked_at >= datetime('now', '-24 hours')
            GROUP BY p.probe_id
            ORDER BY p.is_self DESC, p.region, p.probe_id
            """
        ).fetchall()
        return [
            {**dict(row), "is_self": bool(row["is_self"]), "alive": int(row["alive"] or 0)}
            for row in rows
        ]

    def node_regions(
        self, fingerprints: list[str], *, within_hours: int = 24
    ) -> dict[str, dict[str, dict[str, object]]]:
        """fingerprint -> region -> aggregated fresh status across that region's probes."""
        if not fingerprints:
            return {}
        result: dict[str, dict[str, dict[str, object]]] = {}
        # Chunked IN-lists keep under SQLite's variable limit.
        for start in range(0, len(fingerprints), 500):
            chunk = fingerprints[start:start + 500]
            marks = ",".join("?" for _ in chunk)
            rows = self.connection.execute(
                f"""
                SELECT s.fingerprint, COALESCE(p.region, '??') AS region, s.alive,
                       s.latency_ms, s.checked_at
                FROM node_probe_status s
                LEFT JOIN probes p ON p.probe_id = s.probe_id
                WHERE s.fingerprint IN ({marks})
                  AND s.checked_at >= datetime('now', ?)
                """,
                [*chunk, f"-{int(within_hours)} hours"],
            ).fetchall()
            for row in rows:
                regions = result.setdefault(row["fingerprint"], {})
                info = regions.setdefault(
                    row["region"],
                    {"alive": False, "latency_ms": None, "checked_at": None, "probes": 0},
                )
                info["probes"] = int(info["probes"]) + 1  # type: ignore[call-overload]
                if row["alive"]:
                    info["alive"] = True
                    latency = row["latency_ms"]
                    if latency is not None and (
                        info["latency_ms"] is None or latency < info["latency_ms"]  # type: ignore[operator]
                    ):
                        info["latency_ms"] = latency
                if info["checked_at"] is None or row["checked_at"] > info["checked_at"]:  # type: ignore[operator]
                    info["checked_at"] = row["checked_at"]
        return result

    def _compute_scores(
        self,
        fingerprint: str,
        latency_ms: float | None,
        alive: bool | None,
    ) -> tuple[float, float, float | None, float, float | None]:
        """Return (quality, stability, jitter, recent_rate, latency).

        ``latency`` is the median of recent successful probes (``None`` for a
        node that is down now), so one slow probe does not reshuffle ranking.
        """
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
        recent_rate = weighted_success_rate([bool(row["alive"]) for row in recent])
        recent_latencies = [
            float(row["latency_ms"])
            for row in recent
            if row["alive"] and row["latency_ms"] is not None
        ]
        jitter = pstdev(recent_latencies) if len(recent_latencies) >= 2 else None
        latency = representative_latency(recent_latencies) if alive else None
        if latency is None and alive:
            latency = latency_ms
        stats = HealthStats(
            attempts=successes + failures,
            successes=successes,
            failures=failures,
            latency_ms=latency,
            jitter_ms=jitter,
            recent_success_rate=recent_rate,
        )
        return (
            quality_score(stats, alive=alive),
            stability_score(stats),
            jitter,
            recent_rate,
            None if latency is None else round(latency, 1),
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
            score, stable, jitter, recent_rate, latency = self._compute_scores(
                row["fingerprint"], row["latency_ms"], alive
            )
            self.connection.execute(
                """
                UPDATE nodes SET jitter_ms=?, recent_success_rate=?,
                    stability_score=?, quality_score=?, latency_ms=?
                WHERE fingerprint=?
                """,
                (jitter, recent_rate, stable, score, latency, row["fingerprint"]),
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
        records = [self._row_to_ranked(row) for row in rows]
        regions = self.node_regions([item.node.fingerprint for item in records])
        for item in records:
            item.regions = regions.get(item.node.fingerprint, {})
        return records

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
        if row is None:
            return None
        record = self._row_to_ranked(row)
        record.regions = self.node_regions([fingerprint]).get(fingerprint, {})
        return record

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

    def fingerprints_with_country(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT fingerprint FROM nodes WHERE country IS NOT NULL AND country != ''"
        ).fetchall()
        return {row["fingerprint"] for row in rows}

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
        dead_recheck_minutes: int | None = None,
    ) -> list[ProxyNode]:
        """Pick nodes for validation without starving re-checks.

        Nodes that were never checked and nodes due for a re-check share the
        budget (``new_share`` of it goes to new nodes); any unused part of one
        half is given to the other. Nodes not seen in sources for
        ``seen_within_hours`` are skipped.
        """
        if dead_recheck_minutes is None:
            dead_recheck_minutes = max(int(recheck_after_minutes) * 6, 360)
        seen_clause = ""
        seen_params: list[object] = []
        if seen_within_hours is not None:
            seen_clause = " AND last_seen >= datetime('now', ?)"
            seen_params.append(f"-{max(0, int(seen_within_hours))} hours")

        def fetch_new(count: int | None) -> list[sqlite3.Row]:
            sql = (
                "SELECT * FROM nodes WHERE last_checked IS NULL"
                + seen_clause
                # Nodes another probe already saw alive first: the local probe
                # then spends its budget confirming them from its own network.
                + " ORDER BY remote_alive_at IS NULL, last_seen DESC, RANDOM()"
            )
            params = list(seen_params)
            if count is not None:
                sql += " LIMIT ?"
                params.append(count)
            return self.connection.execute(sql, params).fetchall()

        def fetch_due(count: int | None) -> list[sqlite3.Row]:
            # Previously alive nodes first, then the longest-unchecked ones.
            # Dead nodes back off to dead_recheck_minutes.
            sql = (
                "SELECT * FROM nodes WHERE last_checked IS NOT NULL"
                " AND ((alive = 1 AND last_checked <= datetime('now', ?))"
                " OR (COALESCE(alive, 0) = 0 AND last_checked <= datetime('now', ?)))"
                + seen_clause
                + " ORDER BY CASE WHEN alive = 1 THEN 0 ELSE 1 END,"
                " last_checked ASC, quality_score DESC"
            )
            params: list[object] = [
                f"-{max(0, int(recheck_after_minutes))} minutes",
                f"-{max(0, int(dead_recheck_minutes))} minutes",
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

    def cleanup(
        self,
        *,
        unseen_days: int = 3,
        dead_unseen_hours: int = 24,
    ) -> dict[str, int]:
        """Delete nodes that sources no longer publish.

        - any node not seen in sources for ``unseen_days``;
        - a dead node not seen for ``dead_unseen_hours``.

        Dead nodes that sources still publish are kept (deleting them would
        just re-add them as "new" on the next collect); instead they are
        re-checked less often, see ``list_validation_candidates``.
        """
        conditions = {
            "unseen": ("last_seen < datetime('now', ?)", [f"-{int(unseen_days)} days"]),
            "dead_unseen": (
                "alive = 0 AND last_seen < datetime('now', ?)",
                [f"-{int(dead_unseen_hours)} hours"],
            ),
        }
        removed: dict[str, int] = {}
        for reason, (where, params) in conditions.items():
            self.connection.execute(
                f"DELETE FROM health_checks WHERE fingerprint IN "
                f"(SELECT fingerprint FROM nodes WHERE {where})",
                params,
            )
            self.connection.execute(
                f"DELETE FROM node_probe_status WHERE fingerprint IN "
                f"(SELECT fingerprint FROM nodes WHERE {where})",
                params,
            )
            cursor = self.connection.execute(f"DELETE FROM nodes WHERE {where}", params)
            removed[reason] = cursor.rowcount
        self.connection.execute(
            "DELETE FROM node_probe_status WHERE checked_at < datetime('now', '-7 days')"
        )
        self.connection.commit()
        removed["total"] = sum(removed.values())
        return removed

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
