"""Embedded vector memory with external OpenAI-compatible embeddings."""

from __future__ import annotations

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
from fagent.memory.types import EmbeddingCacheEntry, EpisodeRecord, MemoryArtifact, RetrievedMemory
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
                with httpx.Client(timeout=self.timeout_s) as client:
                    response = client.post(
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
                    content_hash TEXT NOT NULL,
                    embedding_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def healthcheck(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def upsert(
        self,
        record_id: str,
        content: str,
        vector: list[float],
        metadata: dict[str, Any],
        content_hash: str,
        embedding_version: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vectors(id, content, vector_json, metadata_json, content_hash, embedding_version)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    content=excluded.content,
                    vector_json=excluded.vector_json,
                    metadata_json=excluded.metadata_json,
                    content_hash=excluded.content_hash,
                    embedding_version=excluded.embedding_version,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    record_id,
                    content,
                    json.dumps(vector),
                    json.dumps(metadata, ensure_ascii=False),
                    content_hash,
                    embedding_version,
                ),
            )

    def get(self, record_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM vectors WHERE id = ?", (record_id,)).fetchone()

    def query(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[sqlite3.Row]:
        filters = filters or {}
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM vectors").fetchall()

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            if any(metadata.get(key) != value for key, value in filters.items()):
                continue
            vector = json.loads(row["vector_json"])
            score = _cosine_similarity(query_vector, vector)
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
    ):
        self.store = EmbeddedVectorStore(workspace, collection=collection)
        self.batch_size = batch_size
        self.cache_ttl_s = cache_ttl_s
        self.registry = registry
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

    def _cache_expired(self, entry: EmbeddingCacheEntry | None) -> bool:
        if entry is None or not entry.expires_at:
            return False
        return entry.expires_at < time.strftime("%Y-%m-%dT%H:%M:%S")

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
            vectors = self.embedding_client.embed_texts(texts)
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

        for record_id, content, metadata, _artifact_type in records:
            vector = vectors_by_id[record_id]
            payload = {"artifact_id": record_id, **metadata}
            self.store.upsert(
                record_id,
                content,
                vector,
                payload,
                self._content_hash(content),
                self.embedding_client.embedding_version,
            )

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

    def ingest_artifact(self, artifact: MemoryArtifact) -> None:
        self._embed_records(
            [(
                artifact.id,
                artifact.summary or artifact.content,
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

    def ingest_artifacts(self, artifacts: list[MemoryArtifact]) -> int:
        records = [
            (
                artifact.id,
                artifact.summary or artifact.content,
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
            )
            for artifact in artifacts
        ]
        self._embed_records(records)
        return len(records)

    def retrieve(self, query: str, limit: int = 5) -> list[RetrievedMemory]:
        if not self.healthcheck():
            return []
        assert self.embedding_client is not None
        query_vector = self.embedding_client.embed_texts([query])[0]
        rows = self.store.query(query_vector, top_k=limit)
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
