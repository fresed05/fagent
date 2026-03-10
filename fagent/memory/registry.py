"""SQLite-backed registry for memory artifacts and ingest bookkeeping."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fagent.memory.types import (
    EmbeddingCacheEntry,
    ExperiencePattern,
    GraphExtractionJob,
    MemoryArtifact,
    TaskNode,
)
from fagent.utils.helpers import ensure_dir


class MemoryRegistry:
    """Persistent registry tracking artifacts, jobs, and graph edges."""

    def __init__(self, workspace: Path):
        self.base_dir = ensure_dir(workspace / "memory")
        self.db_path = self.base_dir / "registry.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ingest_jobs (
                    episode_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    retries INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS graph_edges (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, relation)
                );
                CREATE TABLE IF NOT EXISTS graph_layouts (
                    node_id TEXT PRIMARY KEY,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    artifact_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding_version TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    artifact_type TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT,
                    PRIMARY KEY (artifact_id, content_hash, embedding_version)
                );
                CREATE TABLE IF NOT EXISTS graph_jobs (
                    job_id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    prompt_version TEXT NOT NULL,
                    model_role TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS task_nodes (
                    task_id TEXT NOT NULL,
                    session_key TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_artifact_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, node_id)
                );
                CREATE TABLE IF NOT EXISTS task_edges (
                    task_id TEXT NOT NULL,
                    source_node_id TEXT NOT NULL,
                    target_node_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (task_id, source_node_id, target_node_id, relation)
                );
                CREATE TABLE IF NOT EXISTS workflow_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    goal TEXT NOT NULL,
                    current_state TEXT NOT NULL,
                    open_blockers_json TEXT NOT NULL,
                    next_step TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    tools_used_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experience_events (
                    event_id TEXT PRIMARY KEY,
                    pattern_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    trigger_text TEXT NOT NULL,
                    recovery_text TEXT NOT NULL,
                    session_key TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_rollups (
                    summary_id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    covered_turns_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    open_items_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def upsert_artifact(self, artifact: MemoryArtifact) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts(id, type, content, summary, metadata_json, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type=excluded.type,
                    content=excluded.content,
                    summary=excluded.summary,
                    metadata_json=excluded.metadata_json,
                    source_ref=excluded.source_ref,
                    created_at=excluded.created_at
                """,
                (
                    artifact.id,
                    artifact.type,
                    artifact.content,
                    artifact.summary,
                    json.dumps(artifact.metadata, ensure_ascii=False),
                    artifact.source_ref,
                    artifact.created_at,
                ),
            )

    def get_artifact(self, artifact_id: str) -> MemoryArtifact | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if not row:
            return None
        return MemoryArtifact(
            id=row["id"],
            type=row["type"],
            content=row["content"],
            summary=row["summary"],
            metadata=json.loads(row["metadata_json"]),
            source_ref=row["source_ref"],
            created_at=row["created_at"],
        )

    def list_artifacts(self, artifact_type: str | None = None, limit: int = 50) -> list[MemoryArtifact]:
        sql = "SELECT * FROM artifacts"
        params: tuple[Any, ...] = ()
        if artifact_type:
            sql += " WHERE type = ?"
            params = (artifact_type,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params += (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            MemoryArtifact(
                id=row["id"],
                type=row["type"],
                content=row["content"],
                summary=row["summary"],
                metadata=json.loads(row["metadata_json"]),
                source_ref=row["source_ref"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def set_job_status(self, episode_id: str, status: str, error: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_jobs(episode_id, status, retries, last_error)
                VALUES (?, ?, CASE WHEN ? = 'retry' THEN 1 ELSE 0 END, ?)
                ON CONFLICT(episode_id) DO UPDATE SET
                    status=excluded.status,
                    retries=CASE
                        WHEN excluded.status = 'retry' THEN ingest_jobs.retries + 1
                        ELSE ingest_jobs.retries
                    END,
                    last_error=excluded.last_error,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (episode_id, status, status, error),
            )

    def get_job_status(self, episode_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM ingest_jobs WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
        return row["status"] if row else None

    def upsert_graph_node(self, node_id: str, label: str, metadata: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO graph_nodes(id, label, metadata_json)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    label=excluded.label,
                    metadata_json=excluded.metadata_json
                """,
                (node_id, label, json.dumps(metadata, ensure_ascii=False)),
            )

    def upsert_graph_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float,
        metadata: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO graph_edges(source_id, target_id, relation, weight, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_id, target_id, relation) DO UPDATE SET
                    weight=excluded.weight,
                    metadata_json=excluded.metadata_json
                """,
                (source_id, target_id, relation, weight, json.dumps(metadata, ensure_ascii=False)),
            )

    def query_graph(self, query: str, limit: int = 8) -> list[sqlite3.Row]:
        like = f"%{query.lower()}%"
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT n.id, n.label, n.metadata_json, e.target_id, e.relation, e.weight, e.metadata_json AS edge_metadata
                FROM graph_nodes n
                LEFT JOIN graph_edges e ON e.source_id = n.id
                WHERE lower(n.label) LIKE ? OR lower(n.metadata_json) LIKE ?
                ORDER BY e.weight DESC
                LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()

    def get_graph_node(self, node_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM graph_nodes WHERE id = ?",
                (node_id,),
            ).fetchone()

    def find_graph_nodes(self, query: str, limit: int = 8) -> list[sqlite3.Row]:
        like = f"%{query.lower()}%"
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT * FROM graph_nodes
                WHERE lower(id) LIKE ? OR lower(label) LIKE ? OR lower(metadata_json) LIKE ?
                ORDER BY label ASC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()

    def get_graph_edges_for_node(self, node_id: str, limit: int = 16) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT source_id, target_id, relation, weight, metadata_json
                FROM graph_edges
                WHERE source_id = ? OR target_id = ?
                ORDER BY weight DESC
                LIMIT ?
                """,
                (node_id, node_id, limit),
            ).fetchall()

    def get_graph_edge(self, source_id: str, target_id: str, relation: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT source_id, target_id, relation, weight, metadata_json
                FROM graph_edges
                WHERE source_id = ? AND target_id = ? AND relation = ?
                """,
                (source_id, target_id, relation),
            ).fetchone()

    def list_graph_nodes(
        self,
        *,
        query: str | None = None,
        node_ids: list[str] | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT n.*, (
                SELECT COUNT(*) FROM graph_edges e
                WHERE e.source_id = n.id OR e.target_id = n.id
            ) AS degree
            FROM graph_nodes n
        """
        params: list[Any] = []
        clauses: list[str] = []
        if query:
            like = f"%{query.lower()}%"
            clauses.append("(lower(n.id) LIKE ? OR lower(n.label) LIKE ? OR lower(n.metadata_json) LIKE ?)")
            params.extend([like, like, like])
        if node_ids:
            placeholders = ", ".join("?" for _ in node_ids)
            clauses.append(f"n.id IN ({placeholders})")
            params.extend(node_ids)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY degree DESC, n.rowid DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(sql, tuple(params)).fetchall()

    def list_graph_edges(
        self,
        *,
        node_ids: list[str] | None = None,
        limit: int = 400,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT source_id, target_id, relation, weight, metadata_json
            FROM graph_edges
        """
        params: list[Any] = []
        if node_ids:
            placeholders = ", ".join("?" for _ in node_ids)
            sql += f" WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})"
            params.extend(node_ids)
            params.extend(node_ids)
        sql += " ORDER BY weight DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(sql, tuple(params)).fetchall()

    def recent_graph_node_ids_for_session(self, session_key: str, limit: int = 200) -> list[str]:
        if not session_key:
            return []
        like = f"%{session_key.lower()}%"
        with self._connect() as conn:
            episode_rows = conn.execute(
                """
                SELECT id FROM graph_nodes
                WHERE lower(metadata_json) LIKE ?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (like, max(1, limit // 4)),
            ).fetchall()
            episode_ids = [str(row["id"]) for row in episode_rows]
            if not episode_ids:
                return []
            placeholders = ", ".join("?" for _ in episode_ids)
            neighbor_rows = conn.execute(
                f"""
                SELECT DISTINCT CASE
                    WHEN source_id IN ({placeholders}) THEN target_id
                    ELSE source_id
                END AS id
                FROM graph_edges
                WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})
                LIMIT ?
                """,
                tuple(episode_ids + episode_ids + episode_ids + [limit]),
            ).fetchall()
        ids = episode_ids + [str(row["id"]) for row in neighbor_rows if row["id"]]
        seen: set[str] = set()
        result: list[str] = []
        for item in ids:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result[:limit]

    def delete_graph_node(self, node_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
            conn.execute("DELETE FROM graph_layouts WHERE node_id = ?", (node_id,))
            conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))

    def delete_graph_edge(self, source_id: str, target_id: str, relation: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM graph_edges
                WHERE source_id = ? AND target_id = ? AND relation = ?
                """,
                (source_id, target_id, relation),
            )

    def save_graph_layouts(self, items: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO graph_layouts(node_id, x, y, pinned, updated_at)
                VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                ON CONFLICT(node_id) DO UPDATE SET
                    x=excluded.x,
                    y=excluded.y,
                    pinned=excluded.pinned,
                    updated_at=COALESCE(excluded.updated_at, CURRENT_TIMESTAMP)
                """,
                [
                    (
                        str(item["node_id"]),
                        float(item["x"]),
                        float(item["y"]),
                        1 if item.get("pinned") else 0,
                        item.get("updated_at"),
                    )
                    for item in items
                ],
            )

    def load_graph_layouts(self, node_ids: list[str] | None = None) -> list[sqlite3.Row]:
        sql = "SELECT node_id, x, y, pinned, updated_at FROM graph_layouts"
        params: list[Any] = []
        if node_ids:
            placeholders = ", ".join("?" for _ in node_ids)
            sql += f" WHERE node_id IN ({placeholders})"
            params.extend(node_ids)
        with self._connect() as conn:
            return conn.execute(sql, tuple(params)).fetchall()

    def put_embedding_cache(self, entry: EmbeddingCacheEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO embedding_cache(
                    artifact_id, content_hash, embedding_version, vector_json, artifact_type, updated_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id, content_hash, embedding_version) DO UPDATE SET
                    vector_json=excluded.vector_json,
                    artifact_type=excluded.artifact_type,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at
                """,
                (
                    entry.artifact_id,
                    entry.content_hash,
                    entry.embedding_version,
                    json.dumps(entry.vector),
                    entry.artifact_type,
                    entry.updated_at,
                    entry.expires_at,
                ),
            )

    def get_embedding_cache(
        self,
        artifact_id: str,
        content_hash: str,
        embedding_version: str,
    ) -> EmbeddingCacheEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM embedding_cache
                WHERE artifact_id = ? AND content_hash = ? AND embedding_version = ?
                """,
                (artifact_id, content_hash, embedding_version),
            ).fetchone()
        if not row:
            return None
        return EmbeddingCacheEntry(
            artifact_id=row["artifact_id"],
            content_hash=row["content_hash"],
            embedding_version=row["embedding_version"],
            vector=json.loads(row["vector_json"]),
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            artifact_type=row["artifact_type"],
        )

    def clear_embedding_cache(self, embedding_version: str | None = None) -> None:
        with self._connect() as conn:
            if embedding_version:
                conn.execute("DELETE FROM embedding_cache WHERE embedding_version = ?", (embedding_version,))
            else:
                conn.execute("DELETE FROM embedding_cache")

    def upsert_graph_job(self, job: GraphExtractionJob) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO graph_jobs(job_id, episode_id, summary, status, attempts, prompt_version, model_role)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    summary=excluded.summary,
                    status=excluded.status,
                    attempts=excluded.attempts,
                    prompt_version=excluded.prompt_version,
                    model_role=excluded.model_role,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    job.job_id,
                    job.episode_id,
                    job.summary,
                    job.status,
                    job.attempts,
                    job.prompt_version,
                    job.model_role,
                ),
            )

    def get_graph_job(self, episode_id: str) -> GraphExtractionJob | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM graph_jobs
                WHERE episode_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (episode_id,),
            ).fetchone()
        if not row:
            return None
        return GraphExtractionJob(
            job_id=row["job_id"],
            episode_id=row["episode_id"],
            summary=row["summary"],
            status=row["status"],
            attempts=row["attempts"],
            prompt_version=row["prompt_version"],
            model_role=row["model_role"],
        )

    def upsert_task_node(self, node: TaskNode, metadata: dict[str, Any] | None = None) -> None:
        meta = metadata or {}
        node_id = str(meta.get("node_id") or f"{node.node_type}:{node.title}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_nodes(task_id, session_key, node_id, node_type, title, status, summary, source_artifact_id, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, node_id) DO UPDATE SET
                    status=excluded.status,
                    summary=excluded.summary,
                    source_artifact_id=excluded.source_artifact_id,
                    metadata_json=excluded.metadata_json
                """,
                (
                    node.task_id,
                    node.session_key,
                    node_id,
                    node.node_type,
                    node.title,
                    node.status,
                    node.summary,
                    node.source_artifact_id,
                    json.dumps(meta, ensure_ascii=False),
                    node.created_at,
                ),
            )

    def upsert_task_edge(
        self,
        task_id: str,
        source_node_id: str,
        target_node_id: str,
        relation: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_edges(task_id, source_node_id, target_node_id, relation, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id, source_node_id, target_node_id, relation) DO UPDATE SET
                    metadata_json=excluded.metadata_json
                """,
                (task_id, source_node_id, target_node_id, relation, json.dumps(metadata or {}, ensure_ascii=False)),
            )

    def list_task_nodes(self, session_key: str, limit: int = 32) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT * FROM task_nodes
                WHERE session_key = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_key, limit),
            ).fetchall()

    def query_task_nodes(self, session_key: str, query: str, limit: int = 10) -> list[sqlite3.Row]:
        like = f"%{query.lower()}%"
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT * FROM task_nodes
                WHERE session_key = ? AND (
                    lower(title) LIKE ? OR lower(summary) LIKE ? OR lower(metadata_json) LIKE ?
                )
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_key, like, like, like, limit),
            ).fetchall()

    def search_task_nodes(self, query: str, limit: int = 10) -> list[sqlite3.Row]:
        like = f"%{query.lower()}%"
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT * FROM task_nodes
                WHERE lower(title) LIKE ? OR lower(summary) LIKE ? OR lower(metadata_json) LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()

    def get_task_edges_for_node(self, task_id: str, node_id: str, limit: int = 16) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT * FROM task_edges
                WHERE task_id = ? AND (source_node_id = ? OR target_node_id = ?)
                ORDER BY relation ASC
                LIMIT ?
                """,
                (task_id, node_id, node_id, limit),
            ).fetchall()

    def insert_workflow_snapshot(
        self,
        snapshot_id: str,
        session_key: str,
        turn_id: str,
        step_index: int,
        goal: str,
        current_state: str,
        open_blockers: list[str],
        next_step: str,
        citations: list[str],
        tools_used: list[str],
        created_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_snapshots(
                    snapshot_id, session_key, turn_id, step_index, goal, current_state, open_blockers_json, next_step, citations_json, tools_used_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    current_state=excluded.current_state,
                    open_blockers_json=excluded.open_blockers_json,
                    next_step=excluded.next_step,
                    citations_json=excluded.citations_json,
                    tools_used_json=excluded.tools_used_json
                """,
                (
                    snapshot_id,
                    session_key,
                    turn_id,
                    step_index,
                    goal,
                    current_state,
                    json.dumps(open_blockers, ensure_ascii=False),
                    next_step,
                    json.dumps(citations, ensure_ascii=False),
                    json.dumps(tools_used, ensure_ascii=False),
                    created_at,
                ),
            )

    def latest_workflow_snapshots(self, session_key: str, limit: int = 8) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT * FROM workflow_snapshots
                WHERE session_key = ?
                ORDER BY created_at DESC, step_index DESC
                LIMIT ?
                """,
                (session_key, limit),
            ).fetchall()

    def insert_experience_event(
        self,
        event_id: str,
        pattern_key: str,
        category: str,
        trigger_text: str,
        recovery_text: str,
        session_key: str,
        metadata: dict[str, Any],
        created_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO experience_events(
                    event_id, pattern_key, category, trigger_text, recovery_text, session_key, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    pattern_key,
                    category,
                    trigger_text,
                    recovery_text,
                    session_key,
                    json.dumps(metadata, ensure_ascii=False),
                    created_at,
                ),
            )

    def get_experience_pattern(self, pattern_key: str) -> ExperiencePattern | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT pattern_key, category, MAX(trigger_text) AS trigger_text, MAX(recovery_text) AS recovery_text,
                       COUNT(*) AS evidence_count, MAX(created_at) AS last_seen_at
                FROM experience_events
                WHERE pattern_key = ?
                GROUP BY pattern_key, category
                """,
                (pattern_key,),
            ).fetchone()
        if not row:
            return None
        return ExperiencePattern(
            pattern_key=row["pattern_key"],
            category=row["category"],
            trigger=row["trigger_text"],
            recovery=row["recovery_text"],
            evidence_count=row["evidence_count"],
            last_seen_at=row["last_seen_at"],
        )

    def list_experience_patterns(self, session_key: str | None = None, limit: int = 16) -> list[ExperiencePattern]:
        sql = """
            SELECT pattern_key, category, MAX(trigger_text) AS trigger_text, MAX(recovery_text) AS recovery_text,
                   COUNT(*) AS evidence_count, MAX(created_at) AS last_seen_at
            FROM experience_events
        """
        params: tuple[Any, ...] = ()
        if session_key:
            sql += " WHERE session_key = ?"
            params = (session_key,)
        sql += " GROUP BY pattern_key, category ORDER BY last_seen_at DESC LIMIT ?"
        params += (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            ExperiencePattern(
                pattern_key=row["pattern_key"],
                category=row["category"],
                trigger=row["trigger_text"],
                recovery=row["recovery_text"],
                evidence_count=row["evidence_count"],
                last_seen_at=row["last_seen_at"],
            )
            for row in rows
        ]

    def insert_session_rollup(
        self,
        summary_id: str,
        session_key: str,
        covered_turns: list[str],
        summary: str,
        open_items: list[str],
        source_refs: list[str],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO session_rollups(summary_id, session_key, covered_turns_json, summary, open_items_json, source_refs_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    summary_id,
                    session_key,
                    json.dumps(covered_turns, ensure_ascii=False),
                    summary,
                    json.dumps(open_items, ensure_ascii=False),
                    json.dumps(source_refs, ensure_ascii=False),
                ),
            )

    def latest_session_rollup(self, session_key: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT * FROM session_rollups
                WHERE session_key = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_key,),
            ).fetchone()
