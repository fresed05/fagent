"""Embedded vector memory with external OpenAI-compatible embeddings."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from fagent.memory.registry import MemoryRegistry
from fagent.memory.types import (
    EmbeddingCacheEntry,
    EpisodeRecord,
    MemoryArtifact,
    RetrievedMemory,
    WorkflowStateArtifact,
)
from fagent.utils.helpers import ensure_dir


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity between two vectors."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class OpenAICompatibleEmbeddingClient:
    """Thin embeddings client for OpenAI-compatible APIs."""

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        *,
        dimensions: int | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout_s: int = 30,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.extra_headers = extra_headers or {}
        self.timeout_s = timeout_s
        self._client = httpx.Client(timeout=self.timeout_s)
        fingerprint = {
            "api_base": self.api_base,
            "model": self.model,
            "dimensions": self.dimensions,
        }
        self.embedding_version = hashlib.sha1(
            json.dumps(fingerprint, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)
        return headers

    def healthcheck(self) -> bool:
        return bool(self.api_base and self.api_key and self.model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts through the configured endpoint."""
        if not self.healthcheck():
            raise RuntimeError("Embedding client is not configured")
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.post(
                    f"{self.api_base}/embeddings",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                break
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(0.25 * (attempt + 1))
        else:
            raise RuntimeError(f"Embedding request failed: {last_error}")
        items = data.get("data")
        if not isinstance(items, list):
            raise ValueError("Embedding response missing data list")
        vectors: list[list[float]] = []
        for item in items:
            embedding = item.get("embedding")
            if not isinstance(embedding, list):
                raise ValueError("Embedding response item missing embedding list")
            vectors.append([float(value) for value in embedding])
        if len(vectors) != len(texts):
            raise ValueError(
                f"Embedding response size mismatch: expected {len(texts)}, got {len(vectors)}"
            )
        return vectors


class EmbeddedVectorStore:
    """SQLite-backed in-process vector store."""

    def __init__(self, workspace: Path, collection: str = "memory"):
        self.base_dir = ensure_dir(workspace / "memory" / "vector")
        self.db_path = self.base_dir / f"{collection}.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    session_key TEXT NOT NULL DEFAULT '',
                    artifact_type TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL DEFAULT '',
                    chat_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    search_text TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    embedding_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(vectors)").fetchall()
            }
            for column_name, definition in {
                "session_key": "TEXT NOT NULL DEFAULT ''",
                "artifact_type": "TEXT NOT NULL DEFAULT ''",
                "channel": "TEXT NOT NULL DEFAULT ''",
                "chat_id": "TEXT NOT NULL DEFAULT ''",
                "turn_id": "TEXT NOT NULL DEFAULT ''",
                "search_text": "TEXT NOT NULL DEFAULT ''",
            }.items():
                if column_name not in columns:
                    conn.execute(f"ALTER TABLE vectors ADD COLUMN {column_name} {definition}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vectors_session_type ON vectors(session_key, artifact_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vectors_artifact_type ON vectors(artifact_type)")

    def healthcheck(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def upsert_many(
        self,
        rows: list[tuple[str, str, list[float], dict[str, Any], str, str]],
    ) -> None:
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO vectors(
                    id, content, vector_json, metadata_json, session_key, artifact_type, channel, chat_id, turn_id, search_text,
                    content_hash, embedding_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    content=excluded.content,
                    vector_json=excluded.vector_json,
                    metadata_json=excluded.metadata_json,
                    session_key=excluded.session_key,
                    artifact_type=excluded.artifact_type,
                    channel=excluded.channel,
                    chat_id=excluded.chat_id,
                    turn_id=excluded.turn_id,
                    search_text=excluded.search_text,
                    content_hash=excluded.content_hash,
                    embedding_version=excluded.embedding_version,
                    updated_at=CURRENT_TIMESTAMP
                """,
                [
                    (
                        record_id,
                        content,
                        json.dumps(vector),
                        json.dumps(metadata, ensure_ascii=False),
                        str(metadata.get("session_key") or ""),
                        str(metadata.get("artifact_type") or ""),
                        str(metadata.get("channel") or ""),
                        str(metadata.get("chat_id") or ""),
                        str(metadata.get("turn_id") or ""),
                        self._build_search_text(content, metadata),
                        content_hash,
                        embedding_version,
                    )
                    for record_id, content, vector, metadata, content_hash, embedding_version in rows
                ],
            )

    def upsert(
        self,
        record_id: str,
        content: str,
        vector: list[float],
        metadata: dict[str, Any],
        content_hash: str,
        embedding_version: str,
    ) -> None:
        session_key = str(metadata.get("session_key") or "")
        artifact_type = str(metadata.get("artifact_type") or "")
        channel = str(metadata.get("channel") or "")
        chat_id = str(metadata.get("chat_id") or "")
        turn_id = str(metadata.get("turn_id") or "")
        search_text = self._build_search_text(content, metadata)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vectors(
                    id, content, vector_json, metadata_json, session_key, artifact_type, channel, chat_id, turn_id, search_text,
                    content_hash, embedding_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    content=excluded.content,
                    vector_json=excluded.vector_json,
                    metadata_json=excluded.metadata_json,
                    session_key=excluded.session_key,
                    artifact_type=excluded.artifact_type,
                    channel=excluded.channel,
                    chat_id=excluded.chat_id,
                    turn_id=excluded.turn_id,
                    search_text=excluded.search_text,
                    content_hash=excluded.content_hash,
                    embedding_version=excluded.embedding_version,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    record_id,
                    content,
                    json.dumps(vector),
                    json.dumps(metadata, ensure_ascii=False),
                    session_key,
                    artifact_type,
                    channel,
                    chat_id,
                    turn_id,
                    search_text,
                    content_hash,
                    embedding_version,
                ),
            )

    @staticmethod
    def _build_search_text(content: str, metadata: dict[str, Any]) -> str:
        parts = [
            content.lower(),
            str(metadata.get("artifact_type") or "").lower(),
            str(metadata.get("source_path") or "").lower(),
            str(metadata.get("turn_id") or "").lower(),
            str(metadata.get("session_key") or "").lower(),
            json.dumps(metadata, ensure_ascii=False, sort_keys=True).lower(),
        ]
        normalized = " ".join(part for part in parts if part)
        compact = "".join(ch for ch in normalized if ch.isalnum())
        return f"{normalized}\n{compact}".strip()

    def get(self, record_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM vectors WHERE id = ?", (record_id,)).fetchone()

    def query(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        query_text: str | None = None,
        candidate_limit: int | None = None,
    ) -> list[sqlite3.Row]:
        filters = filters or {}
        candidate_limit = max(top_k, candidate_limit or max(top_k * 8, 64))
        if query_text:
            candidate_limit = max(candidate_limit, 256 if not filters else 128)
        sql = "SELECT * FROM vectors WHERE 1=1"
        params: list[Any] = []
        if "session_key" in filters:
            sql += " AND session_key = ?"
            params.append(str(filters["session_key"]))
        if "artifact_type" in filters:
            artifact_type = filters["artifact_type"]
            if isinstance(artifact_type, (list, tuple, set)):
                values = [str(item) for item in artifact_type if str(item)]
                if values:
                    placeholders = ", ".join("?" for _ in values)
                    sql += f" AND artifact_type IN ({placeholders})"
                    params.extend(values)
            elif artifact_type:
                sql += " AND artifact_type = ?"
                params.append(str(artifact_type))
        query_text = (query_text or "").strip().lower()
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(candidate_limit)
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            if not rows and filters:
                fallback_sql = "SELECT * FROM vectors WHERE 1=1"
                fallback_params: list[Any] = []
                if "session_key" in filters:
                    fallback_sql += " AND session_key = ?"
                    fallback_params.append(str(filters["session_key"]))
                if "artifact_type" in filters:
                    artifact_type = filters["artifact_type"]
                    if isinstance(artifact_type, (list, tuple, set)):
                        values = [str(item) for item in artifact_type if str(item)]
                        if values:
                            placeholders = ", ".join("?" for _ in values)
                            fallback_sql += f" AND artifact_type IN ({placeholders})"
                            fallback_params.extend(values)
                    elif artifact_type:
                        fallback_sql += " AND artifact_type = ?"
                        fallback_params.append(str(artifact_type))
                fallback_sql += " ORDER BY updated_at DESC LIMIT ?"
                fallback_params.append(candidate_limit)
                rows = conn.execute(fallback_sql, tuple(fallback_params)).fetchall()

        compact_query = "".join(ch for ch in query_text if ch.isalnum())
        search_tokens = [token for token in query_text.split() if len(token) >= 3]
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            vector = json.loads(row["vector_json"])
            score = _cosine_similarity(query_vector, vector)
            if query_text:
                search_text = str(row["search_text"] or "")
                lexical_bonus = 0.0
                if query_text in search_text:
                    lexical_bonus += 0.08
                if compact_query and compact_query in "".join(ch for ch in search_text if ch.isalnum()):
                    lexical_bonus += 0.06
                lexical_bonus += min(0.06, 0.015 * sum(1 for token in search_tokens[:4] if token in search_text))
                score = min(1.0, score + lexical_bonus)
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in scored[:top_k]]


class VectorMemoryBackend:
    """Vector backend using external embeddings and embedded local storage."""

    def __init__(
        self,
        workspace: Path,
        *,
        collection: str = "memory",
        embedding_model: str = "",
        embedding_api_base: str = "",
        embedding_api_key: str = "",
        embedding_dimensions: int = 0,
        embedding_extra_headers: dict[str, str] | None = None,
        batch_size: int = 16,
        request_timeout_s: int = 30,
        cache_ttl_s: int = 0,
        registry: MemoryRegistry | None = None,
        query_cache_max_size: int = 128,
    ):
        self.store = EmbeddedVectorStore(workspace, collection=collection)
        self.batch_size = batch_size
        self.cache_ttl_s = cache_ttl_s
        self.registry = registry
        self.query_cache_max_size = max(8, query_cache_max_size)
        self._query_embedding_cache: OrderedDict[str, tuple[list[float], float]] = OrderedDict()
        self._query_embedding_requests = 0
        self._query_embedding_cache_hits = 0
        self._query_embedding_evictions = 0
        self._query_embedding_ttl_hits = 0
        self._embedding_batches = 0
        self._embedded_records = 0
        self._embedding_network_ms = 0
        self._vector_upsert_ms = 0
        self.embedding_client = None
        if embedding_model and embedding_api_base and embedding_api_key:
            self.embedding_client = OpenAICompatibleEmbeddingClient(
                api_base=embedding_api_base,
                api_key=embedding_api_key,
                model=embedding_model,
                dimensions=embedding_dimensions or None,
                extra_headers=embedding_extra_headers,
                timeout_s=request_timeout_s,
            )

    def healthcheck(self) -> bool:
        return self.store.healthcheck() and self.embedding_client is not None and self.embedding_client.healthcheck()

    def _content_hash(self, content: str) -> str:
        return hashlib.sha1(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _artifact_text(artifact: MemoryArtifact) -> str:
        if artifact.type in {"session_turn", "workflow_state", "experience_pattern", "session_summary"}:
            return artifact.content
        return artifact.summary or artifact.content

    def _cache_expired(self, entry: EmbeddingCacheEntry | None) -> bool:
        if entry is None or not entry.expires_at:
            return False
        return entry.expires_at < time.strftime("%Y-%m-%dT%H:%M:%S")

    def _query_cache_key(self, query: str) -> str:
        return hashlib.sha1(query.strip().lower().encode("utf-8")).hexdigest()

    def embed_query(self, query: str) -> list[float]:
        if self.embedding_client is None:
            return []
        key = self._query_cache_key(query)
        cached = self._query_embedding_cache.get(key)
        if cached is not None:
            vector, cached_at = cached
            if self.cache_ttl_s <= 0 or (time.time() - cached_at) <= self.cache_ttl_s:
                self._query_embedding_cache.move_to_end(key)
                self._query_embedding_cache_hits += 1
                return vector
            self._query_embedding_ttl_hits += 1
            self._query_embedding_cache.pop(key, None)
        started_at = time.perf_counter()
        vector = self.embedding_client.embed_texts([query])[0]
        self._embedding_network_ms += int((time.perf_counter() - started_at) * 1000)
        self._query_embedding_cache[key] = (vector, time.time())
        self._query_embedding_cache.move_to_end(key)
        while len(self._query_embedding_cache) > self.query_cache_max_size:
            self._query_embedding_cache.popitem(last=False)
            self._query_embedding_evictions += 1
        self._query_embedding_requests += 1
        return vector

    def reset_query_embedding_stats(self) -> None:
        self._query_embedding_requests = 0
        self._query_embedding_cache_hits = 0
        self._query_embedding_ttl_hits = 0
        self._embedding_batches = 0
        self._embedded_records = 0
        self._embedding_network_ms = 0
        self._vector_upsert_ms = 0

    def query_embedding_stats(self) -> dict[str, int]:
        return {
            "requests": self._query_embedding_requests,
            "cache_hits": self._query_embedding_cache_hits,
            "ttl_expirations": self._query_embedding_ttl_hits,
            "evictions": self._query_embedding_evictions,
            "cache_size": len(self._query_embedding_cache),
            "embedding_batches": self._embedding_batches,
            "embedded_records": self._embedded_records,
            "embedding_network_ms": self._embedding_network_ms,
            "vector_upsert_ms": self._vector_upsert_ms,
        }

    def _embed_records(self, records: list[tuple[str, str, dict[str, Any], str]]) -> None:
        if self.embedding_client is None or not records:
            return

        pending: list[tuple[str, str, dict[str, Any], str]] = []
        vectors_by_id: dict[str, list[float]] = {}
        for record_id, content, metadata, artifact_type in records:
            content_hash = self._content_hash(content)
            cached_vector = None
            store_row = self.store.get(record_id)
            if (
                store_row
                and store_row["content_hash"] == content_hash
                and store_row["embedding_version"] == self.embedding_client.embedding_version
            ):
                cached_vector = json.loads(store_row["vector_json"])
            if cached_vector is None and self.registry is not None:
                cache_entry = self.registry.get_embedding_cache(
                    record_id,
                    content_hash,
                    self.embedding_client.embedding_version,
                )
                if cache_entry is not None and not self._cache_expired(cache_entry):
                    cached_vector = cache_entry.vector
            if cached_vector is not None:
                vectors_by_id[record_id] = cached_vector
            else:
                pending.append((record_id, content, metadata, artifact_type))

        for index in range(0, len(pending), self.batch_size):
            batch = pending[index:index + self.batch_size]
            texts = [item[1] for item in batch]
            if not texts:
                continue
            started_at = time.perf_counter()
            vectors = self.embedding_client.embed_texts(texts)
            self._embedding_network_ms += int((time.perf_counter() - started_at) * 1000)
            self._embedding_batches += 1
            self._embedded_records += len(texts)
            for (record_id, content, metadata, artifact_type), vector in zip(batch, vectors):
                vectors_by_id[record_id] = vector
                if self.registry is not None:
                    expires_at = None
                    if self.cache_ttl_s > 0:
                        expires_at = time.strftime(
                            "%Y-%m-%dT%H:%M:%S",
                            time.gmtime(time.time() + self.cache_ttl_s),
                        )
                    self.registry.put_embedding_cache(
                        EmbeddingCacheEntry(
                            artifact_id=record_id,
                            content_hash=self._content_hash(content),
                            embedding_version=self.embedding_client.embedding_version,
                            vector=vector,
                            updated_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                            expires_at=expires_at,
                            artifact_type=artifact_type,
                        )
                    )

        upsert_rows = []
        for record_id, content, metadata, _artifact_type in records:
            vector = vectors_by_id[record_id]
            payload = {"artifact_id": record_id, **metadata}
            upsert_rows.append(
                (
                    record_id,
                    content,
                    vector,
                    payload,
                    self._content_hash(content),
                    self.embedding_client.embedding_version,
                )
            )
        if upsert_rows:
            started_at = time.perf_counter()
            self.store.upsert_many(upsert_rows)
            self._vector_upsert_ms += int((time.perf_counter() - started_at) * 1000)

    def ingest_episode(self, episode: EpisodeRecord) -> None:
        self._embed_records(
            [(
                episode.episode_id,
                episode.content,
                {
                "workspace_id": "default",
                "session_key": episode.session_key,
                "chat_id": episode.chat_id,
                "channel": episode.channel,
                "artifact_type": "session_turn",
                "speaker_role": "conversation",
                "timestamp": episode.timestamp,
                "topic_tags": episode.metadata.get("topic_tags", []),
                "source_path": episode.metadata.get("source_path", ""),
                "turn_id": episode.turn_id,
                "embedding_version": self.embedding_client.embedding_version if self.embedding_client else "disabled",
                },
                "session_turn",
            )]
        )

    def _coerce_artifact(self, artifact: MemoryArtifact | WorkflowStateArtifact) -> MemoryArtifact:
        if isinstance(artifact, MemoryArtifact):
            return artifact
        return MemoryArtifact(
            id=f"workflow:{artifact.snapshot_id}",
            type="workflow_state",
            content=artifact.current_state,
            summary=f"{artifact.goal} -> {artifact.current_state}"[:240],
            metadata={
                "session_key": artifact.session_key,
                "turn_id": artifact.turn_id,
                "step_index": artifact.step_index,
                "open_blockers": list(artifact.open_blockers),
                "next_step": artifact.next_step,
                "citations": list(artifact.citations),
                "tools_used": list(artifact.tools_used),
                "artifact_type": "workflow_state",
                "snapshot_id": artifact.snapshot_id,
            },
            source_ref="workflow",
        )

    def ingest_artifact(self, artifact: MemoryArtifact | WorkflowStateArtifact) -> None:
        artifact = self._coerce_artifact(artifact)
        self._embed_records(
            [(
                artifact.id,
                self._artifact_text(artifact),
                {
                "workspace_id": "default",
                "session_key": artifact.metadata.get("session_key", ""),
                "chat_id": artifact.metadata.get("chat_id", ""),
                "channel": artifact.metadata.get("channel", ""),
                "artifact_type": artifact.type,
                "speaker_role": artifact.metadata.get("speaker_role", ""),
                "timestamp": artifact.created_at,
                "topic_tags": artifact.metadata.get("topic_tags", []),
                "source_path": artifact.source_ref,
                "turn_id": artifact.metadata.get("turn_id", ""),
                "embedding_version": self.embedding_client.embedding_version if self.embedding_client else "disabled",
                },
                artifact.type,
            )]
        )

    def ingest_artifacts(self, artifacts: list[MemoryArtifact | WorkflowStateArtifact]) -> int:
        records = [
            (
                coerced.id,
                self._artifact_text(coerced),
                {
                    "workspace_id": "default",
                    "session_key": coerced.metadata.get("session_key", ""),
                    "chat_id": coerced.metadata.get("chat_id", ""),
                    "channel": coerced.metadata.get("channel", ""),
                    "artifact_type": coerced.type,
                    "speaker_role": coerced.metadata.get("speaker_role", ""),
                    "timestamp": coerced.created_at,
                    "topic_tags": coerced.metadata.get("topic_tags", []),
                    "source_path": coerced.source_ref,
                    "turn_id": coerced.metadata.get("turn_id", ""),
                    "embedding_version": self.embedding_client.embedding_version if self.embedding_client else "disabled",
                },
                coerced.type,
            )
            for item in artifacts
            for coerced in [self._coerce_artifact(item)]
        ]
        self._embed_records(records)
        return len(records)

    def retrieve(self, query: str, limit: int = 5, *, filters: dict[str, Any] | None = None) -> list[RetrievedMemory]:
        if not self.healthcheck():
            return []
        assert self.embedding_client is not None
        query_vector = self.embed_query(query)
        rows = self.store.query(
            query_vector,
            top_k=limit,
            filters=filters,
            query_text=query,
        )
        results: list[RetrievedMemory] = []
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            vector = json.loads(row["vector_json"])
            score = _cosine_similarity(query_vector, vector)
            results.append(
                RetrievedMemory(
                    artifact_id=str(metadata.get("artifact_id", row["id"])),
                    store="vector",
                    score=score,
                    snippet=str(row["content"])[:320],
                    reason=f"Semantic match in {metadata.get('artifact_type', 'artifact')}",
                    metadata=metadata,
                )
            )
        return results
