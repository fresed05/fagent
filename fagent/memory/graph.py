"""Graph memory backends and extraction pipeline."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from fagent.memory.policy import MemoryPolicy
from fagent.memory.registry import MemoryRegistry
from fagent.memory.types import EpisodeRecord, GraphExtractionJob, RetrievedMemory
from fagent.memory.vector import _cosine_similarity
from fagent.prompts import PromptLoader
from fagent.providers.base import LLMProvider


_RELATION_SYNONYMS = {
    "uses": "uses",
    "use": "uses",
    "utilizes": "uses",
    "is using": "uses",
    "works with": "uses",
    "использует": "uses",
    "зависит от": "depends_on",
    "depends on": "depends_on",
    "depends_on": "depends_on",
    "supports": "supports",
    "support": "supports",
    "поддерживает": "supports",
    "belongs to": "belongs_to",
    "belongs_to": "belongs_to",
    "отноcится к": "belongs_to",
    "supersedes": "supersedes",
    "mentions": "mentions",
    "упоминает": "mentions",
    "runs on": "runs_on",
    "runs_on": "runs_on",
    "работает на": "runs_on",
    "connects to": "connects_to",
    "connects_to": "connects_to",
    "подключается к": "connects_to",
    "stores in": "stores_in",
    "stores_in": "stores_in",
    "хранит в": "stores_in",
    "blocked by": "blocked_by",
    "blocked_by": "blocked_by",
    "blocked_by": "blocked_by",
    "блокируется": "blocked_by",
    "decided": "decided",
    "решили": "decided",
    "configured with": "configured_with",
    "configured_with": "configured_with",
    "configured": "configured_with",
    "настроен через": "configured_with",
    "relates_to": "mentions",
    "parent_of": "parent_of",
    "child_of": "child_of",
    "groups": "parent_of",
}

_ENGLISH_CANONICAL_MAP = {
    "теневой контекст": "shadow context",
    "shadow context": "shadow context",
    "графовая память": "graph memory",
    "graph memory": "graph memory",
    "память графа": "graph memory",
    "ланседб": "lancedb",
    "лэнсдб": "lancedb",
    "использует lancedb": "uses lancedb",
    "использует": "uses",
    "решение": "decision",
    "рабочий процесс": "workflow",
    "проект": "project",
    "сессия": "session",
}

_GENERIC_ENTITY_WORDS = {
    "good", "look", "thing", "remember", "future", "project", "memory", "graph", "system",
    "штука", "вещь", "память", "граф", "система", "проект",
}


_GRAPH_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_graph",
            "description": "Search existing graph nodes before creating new ones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 32, "default": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_graph_node",
            "description": "Read one existing graph node and its nearby edges.",
            "parameters": {
                "type": "object",
                "properties": {"node_id": {"type": "string"}},
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_entity",
            "description": "Stage one durable entity node. Never create generic filler words.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "label": {"type": "string"},
                    "surface_label": {"type": "string"},
                    "canonical_english_label": {"type": "string"},
                    "kind": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "source_language": {"type": "string"},
                    "language_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "ambiguous_language": {"type": "boolean"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_entities",
            "description": "Stage multiple durable entity nodes in one call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "entity_id": {"type": "string"},
                                "label": {"type": "string"},
                                "surface_label": {"type": "string"},
                                "canonical_english_label": {"type": "string"},
                                "kind": {"type": "string"},
                                "aliases": {"type": "array", "items": {"type": "string"}},
                                "source_language": {"type": "string"},
                                "language_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "ambiguous_language": {"type": "boolean"},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                        },
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_fact",
            "description": "Stage one durable fact node tied to an entity or episode subject.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_id": {"type": "string"},
                    "statement": {"type": "string"},
                    "statement_english": {"type": "string"},
                    "surface_statement": {"type": "string"},
                    "subject_id": {"type": "string"},
                    "source_language": {"type": "string"},
                    "language_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "ambiguous_language": {"type": "boolean"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "supersedes": {"type": "array", "items": {"type": "string"}},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_facts",
            "description": "Stage multiple durable fact nodes in one call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "fact_id": {"type": "string"},
                                "statement": {"type": "string"},
                                "statement_english": {"type": "string"},
                                "surface_statement": {"type": "string"},
                                "subject_id": {"type": "string"},
                                "source_language": {"type": "string"},
                                "language_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "ambiguous_language": {"type": "boolean"},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "supersedes": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_relation",
            "description": "Stage one directed relation between existing or staged nodes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "relation": {"type": "string"},
                    "source_language": {"type": "string"},
                    "language_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "ambiguous_language": {"type": "boolean"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["source_id", "target_id", "relation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_relations",
            "description": "Stage multiple directed relations in one call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_id": {"type": "string"},
                                "target_id": {"type": "string"},
                                "relation": {"type": "string"},
                                "source_language": {"type": "string"},
                                "language_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "ambiguous_language": {"type": "boolean"},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                            "required": ["source_id", "target_id", "relation"],
                        },
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_graph_plan",
            "description": "Finish extraction after all durable updates have been staged.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    },
]


class LocalGraphBackend:
    """SQLite-backed graph memory with tool-driven LLM extraction."""

    def __init__(
        self,
        workspace: Path,
        registry: MemoryRegistry,
        *,
        provider: LLMProvider | None = None,
        extract_model: str | None = None,
        normalize_model: str | None = None,
        prompt_loader: PromptLoader | None = None,
        semantic_embedder: Any | None = None,
    ):
        self.workspace = workspace
        self.registry = registry
        self.policy = MemoryPolicy()
        self.provider = provider
        self.extract_model = extract_model
        self.normalize_model = normalize_model
        self.prompt_loader = prompt_loader or PromptLoader.from_package()
        self.semantic_embedder = semantic_embedder
        self._semantic_payload_cache: dict[str, list[float]] = {}
        self.last_search_candidate_count = 0

    @staticmethod
    def _looks_english(value: str) -> bool:
        text = (value or "").strip()
        if not text:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9 _./:+#()-]+", text))

    @staticmethod
    def _normalize_text(value: str) -> str:
        text = unicodedata.normalize("NFKC", value or "").strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text

    def _detect_language(self, value: str) -> str:
        text = value or ""
        has_cyrillic = any("CYRILLIC" in unicodedata.name(ch, "") for ch in text if ch.isalpha())
        has_latin = any("LATIN" in unicodedata.name(ch, "") for ch in text if ch.isalpha())
        if has_cyrillic and not has_latin:
            return "ru"
        if has_latin and not has_cyrillic:
            return "en"
        if has_cyrillic and has_latin:
            return "mixed"
        return "unknown"

    def _canonicalize_english(self, value: str) -> tuple[str, str, float, str]:
        raw = (value or "").strip()
        normalized = self._normalize_text(raw)
        if not normalized:
            return "", "unknown", 0.0, "empty"
        language = self._detect_language(raw)
        if normalized in _ENGLISH_CANONICAL_MAP:
            return _ENGLISH_CANONICAL_MAP[normalized], language, 0.96, "dictionary"
        if self._looks_english(raw):
            english = re.sub(r"\s+", " ", raw).strip()
            return english, "en", 0.98, "exact"
        token_parts: list[str] = []
        for token in normalized.split():
            mapped = _ENGLISH_CANONICAL_MAP.get(token)
            if mapped:
                token_parts.append(mapped)
            elif re.fullmatch(r"[a-z0-9._:/+-]+", token):
                token_parts.append(token)
            else:
                return "", language, 0.0, "unsupported_language"
        english = re.sub(r"\s+", " ", " ".join(token_parts)).strip()
        if not english or not self._looks_english(english):
            return "", language, 0.0, "unsupported_language"
        confidence = 0.82 if language != "en" else 0.95
        return english, language, confidence, "token_map"

    def _normalize_relation(self, relation: str) -> tuple[str, float]:
        candidate = self._normalize_text(relation).replace("-", "_")
        if candidate in _RELATION_SYNONYMS:
            return _RELATION_SYNONYMS[candidate], 0.98
        if candidate.replace("_", " ") in _RELATION_SYNONYMS:
            return _RELATION_SYNONYMS[candidate.replace("_", " ")], 0.94
        return "", 0.0

    def _build_alias_rows(
        self,
        canonical_label: str,
        aliases: list[str],
        source_label: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for alias_text in [canonical_label, source_label, *aliases]:
            alias = str(alias_text or "").strip()
            if not alias:
                continue
            key = alias.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "alias_text": alias,
                    "alias_language": self._detect_language(alias),
                    "is_canonical": alias == canonical_label,
                }
            )
        return rows

    def _find_existing_entity_id(self, canonical_label: str) -> str | None:
        rows = self._search_graph_candidates(canonical_label, limit=8)
        if not rows:
            fallback_rows = self.registry.list_graph_nodes(limit=96)
            rescored: list[dict[str, Any]] = []
            for row in fallback_rows:
                lexical = self._score_graph_row(canonical_label, row)
                if lexical < 0.58:
                    continue
                rescored.append(
                    {
                        "id": str(row["id"]),
                        "label": str(row["label"]),
                        "metadata_json": str(row["metadata_json"] or "{}"),
                        "search_score": lexical,
                        "semantic_score": 0.0,
                    }
                )
            if rescored:
                semantic_scores = self._semantic_score_graph_rows(canonical_label, rescored[:48])
                for item in rescored:
                    semantic = semantic_scores.get(item["id"], 0.0)
                    item["semantic_score"] = semantic
                    item["search_score"] = max(item["search_score"], semantic, 0.72 * item["search_score"] + 0.28 * semantic)
                rescored.sort(key=lambda item: (item["search_score"], item["semantic_score"], item["label"]), reverse=True)
                rows = rescored[:8]
        for row in rows:
            metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            score = float(row.get("search_score", 0.0))
            semantic_score = float(row.get("semantic_score", 0.0))
            if self._normalize_text(str(metadata.get("canonical_name") or row["label"])) == self._normalize_text(canonical_label):
                return str(row["id"])
            if score >= 0.84 or semantic_score >= 0.9:
                return str(row["id"])
        return None

    def _compact_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", self._normalize_text(value))

    def _candidate_texts(self, row: Any) -> list[str]:
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        texts = [str(row["label"])]
        canonical_name = str(metadata.get("canonical_name") or "").strip()
        if canonical_name:
            texts.append(canonical_name)
        for alias in metadata.get("aliases") or []:
            alias_text = str(alias).strip()
            if alias_text:
                texts.append(alias_text)
        return list(dict.fromkeys(texts))

    def _score_graph_row(self, query: str, row: Any) -> float:
        normalized_query = self._normalize_text(query)
        compact_query = self._compact_key(query)
        best = 0.0
        for text in self._candidate_texts(row):
            normalized_text = self._normalize_text(text)
            compact_text = self._compact_key(text)
            if normalized_text == normalized_query:
                best = max(best, 1.0)
            elif compact_text and compact_text == compact_query:
                best = max(best, 0.985)
            elif normalized_query in normalized_text or normalized_text in normalized_query:
                best = max(best, 0.94)
            elif compact_query and compact_query in compact_text:
                best = max(best, 0.91)
            else:
                best = max(best, SequenceMatcher(None, compact_query or normalized_query, compact_text or normalized_text).ratio())
        return best

    def _semantic_score_graph_rows(self, query: str, rows: list[Any]) -> dict[str, float]:
        if not rows or self.semantic_embedder is None or getattr(self.semantic_embedder, "embedding_client", None) is None:
            return {}
        try:
            if hasattr(self.semantic_embedder, "embed_query"):
                query_vector = self.semantic_embedder.embed_query(query)
            else:
                query_vector = self.semantic_embedder.embedding_client.embed_texts([query])[0]
            payloads = []
            keys = []
            payload_vectors: list[list[float] | None] = []
            for row in rows:
                metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
                payload = " | ".join(self._candidate_texts(row) + [str(metadata.get("kind") or "")])
                payloads.append(payload)
                keys.append((str(row["id"]), payload))
                payload_vectors.append(self._semantic_payload_cache.get(payload))
            missing_payloads = [payload for payload, vector in zip(payloads, payload_vectors) if vector is None]
            if missing_payloads:
                new_vectors = self.semantic_embedder.embedding_client.embed_texts(missing_payloads)
                for payload, vector in zip(missing_payloads, new_vectors):
                    self._semantic_payload_cache[payload] = vector
            scores: dict[str, float] = {}
            for node_id, payload in keys:
                vector = self._semantic_payload_cache.get(payload)
                if vector is None:
                    continue
                scores[node_id] = _cosine_similarity(query_vector, vector)
            return scores
        except Exception as exc:
            logger.debug("Graph semantic search skipped: {}", exc)
            return {}

    def _search_graph_candidates(self, query: str, limit: int = 20, tier_weights: dict[int, float] | None = None) -> list[dict[str, Any]]:
        tier_weights = tier_weights or {1: 2.0, 2: 1.5, 3: 1.0}
        raw_limit = max(limit * 12, 240)
        raw_rows = self.registry.list_graph_nodes(query=query, limit=raw_limit)
        self.last_search_candidate_count = len(raw_rows)
        preliminary: list[dict[str, Any]] = []
        for row in raw_rows:
            lexical = self._score_graph_row(query, row)
            tier = int(row.get("tier", 3))
            preliminary.append(
                {
                    "id": str(row["id"]),
                    "label": str(row["label"]),
                    "metadata_json": str(row["metadata_json"] or "{}"),
                    "tier": tier,
                    "search_score": lexical,
                    "lexical_score": lexical,
                    "semantic_score": 0.0,
                }
            )
        if not preliminary:
            return []
        preliminary.sort(key=lambda item: (item["lexical_score"], item["label"]), reverse=True)
        semantic_scores = self._semantic_score_graph_rows(query, preliminary[:160])
        ranked: list[dict[str, Any]] = []
        for item in preliminary:
            semantic = semantic_scores.get(item["id"], 0.0)
            item["semantic_score"] = semantic
            item["search_score"] = max(item["search_score"], semantic, 0.72 * item["lexical_score"] + 0.28 * semantic)
            tier_boost = tier_weights.get(item["tier"], 1.0)
            item["search_score"] *= tier_boost
            if item["lexical_score"] >= 0.52 or semantic >= 0.72 or item["search_score"] >= 0.7:
                ranked.append(item)
        ranked.sort(key=lambda item: (item["search_score"], -item["tier"], item["semantic_score"], item["label"]), reverse=True)
        return ranked[:limit]

    def search_candidates(self, query: str, limit: int = 20, tier_weights: dict[int, float] | None = None) -> list[dict[str, Any]]:
        """Expose ranked graph candidates for retrieval and diagnostics."""
        return self._search_graph_candidates(query, limit=limit, tier_weights=tier_weights)

    def healthcheck(self) -> bool:
        return True

    def sync_node(self, node_id: str) -> str | None:
        return None

    def sync_edge(self, source_id: str, target_id: str, relation: str) -> str | None:
        return None

    def delete_node(self, node_id: str) -> str | None:
        return None

    def delete_edge(self, source_id: str, target_id: str, relation: str) -> str | None:
        return None

    def _traverse_up(self, node_id: str, max_depth: int, visited: set[str], depth: int = 0) -> list[dict[str, Any]]:
        """Traverse up the hierarchy following parent_of edges."""
        if depth >= max_depth or node_id in visited:
            return []
        visited.add(node_id)
        parents = []
        edges = self.registry.list_graph_edges(target_id=node_id, relation="parent_of")
        for edge in edges:
            parent_id = edge["source_id"]
            parent_node = self.registry.get_graph_node(parent_id)
            if parent_node:
                parents.append({
                    "node": dict(parent_node),
                    "depth": depth + 1,
                    "relation": "parent_of"
                })
                parents.extend(self._traverse_up(parent_id, max_depth, visited, depth + 1))
        return parents

    def _traverse_down(self, node_id: str, max_depth: int, visited: set[str], depth: int = 0) -> list[dict[str, Any]]:
        """Traverse down the hierarchy following child_of edges."""
        if depth >= max_depth or node_id in visited:
            return []
        visited.add(node_id)
        children = []
        edges = self.registry.list_graph_edges(source_id=node_id, relation="parent_of")
        for edge in edges:
            child_id = edge["target_id"]
            child_node = self.registry.get_graph_node(child_id)
            if child_node:
                children.append({
                    "node": dict(child_node),
                    "depth": depth + 1,
                    "relation": "child_of"
                })
                children.extend(self._traverse_down(child_id, max_depth, visited, depth + 1))
        return children

    def traverse_hierarchy(self, start_node_id: str, direction: str = "both", max_depth: int = 3) -> dict[str, Any]:
        """Traverse graph hierarchy from a starting node."""
        start_node = self.registry.get_graph_node(start_node_id)
        if not start_node:
            return {"error": "Node not found", "start_node": None, "parents": [], "children": [], "siblings": []}

        result = {
            "start_node": dict(start_node),
            "parents": [],
            "children": [],
            "siblings": []
        }

        if direction in ("up", "both"):
            result["parents"] = self._traverse_up(start_node_id, max_depth, set())

        if direction in ("down", "both"):
            result["children"] = self._traverse_down(start_node_id, max_depth, set())

        if direction == "both":
            parent_ids = {p["node"]["id"] for p in result["parents"]}
            for parent_id in parent_ids:
                edges = self.registry.list_graph_edges(source_id=parent_id, relation="parent_of")
                for edge in edges:
                    sibling_id = edge["target_id"]
                    if sibling_id != start_node_id:
                        sibling_node = self.registry.get_graph_node(sibling_id)
                        if sibling_node and sibling_node["id"] not in [s["id"] for s in result["siblings"]]:
                            result["siblings"].append(dict(sibling_node))

        return result

    async def ingest_episode_async(
        self,
        episode: EpisodeRecord,
        status_callback: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        summary = self.policy.build_summary(episode)
        extractor_prompt = self.prompt_loader.load("system/memory-extractor.md")
        previous_job = self.registry.get_graph_job(episode.episode_id)
        job = GraphExtractionJob(
            job_id=f"graph-{episode.episode_id}",
            episode_id=episode.episode_id,
            summary=summary,
            status="running",
            attempts=(previous_job.attempts + 1) if previous_job else 1,
            prompt_version=extractor_prompt.version,
            model_role="graph_extract",
            error="",
        )
        self.registry.upsert_graph_job(job)

        if self.provider is None or not self.extract_model:
            job.status = "skipped"
            job.error = "graph_extract_unavailable"
            self.registry.upsert_graph_job(job)
            return

        try:
            extraction = await self._extract_with_llm(
                episode,
                summary,
                extractor_prompt.text,
                status_callback=status_callback,
            )
            if extraction is not None:
                if status_callback is not None:
                    await status_callback("persisting", "persisting graph")
                self._persist_graph(episode, summary, extraction)
            job.status = "done"
            job.error = ""
            self.registry.upsert_graph_job(job)
            if status_callback is not None:
                await status_callback("done", "done")
        except Exception as exc:
            logger.warning("Graph extraction failed for {}: {}", episode.episode_id, exc)
            job.status = "retry"
            job.error = str(exc)[:500]
            self.registry.upsert_graph_job(job)
            if status_callback is not None:
                await status_callback("retry", f"retry: {job.error}", error=job.error)

    def ingest_episode(self, episode: EpisodeRecord) -> None:
        """Sync compatibility wrapper."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.ingest_episode_async(episode))
            return

        if loop.is_running():
            loop.create_task(self.ingest_episode_async(episode))
        else:
            loop.run_until_complete(self.ingest_episode_async(episode))

    async def _extract_with_llm(
        self,
        episode: EpisodeRecord,
        summary: str,
        extractor_prompt: str,
        status_callback: Callable[..., Awaitable[None]] | None = None,
    ) -> dict[str, Any] | None:
        assert self.provider is not None
        assert self.extract_model

        stage: dict[str, Any] = {
            "summary": summary,
            "reason": "",
            "entities": {},
            "facts": {},
            "relations": [],
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": extractor_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "episode_id": episode.episode_id,
                        "session_key": episode.session_key,
                        "turn_id": episode.turn_id,
                        "summary": summary,
                        "user_text": episode.user_text,
                        "assistant_text": episode.assistant_text,
                        "tool_trace": episode.tool_trace,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        for _ in range(5):
            response = await self.provider.chat(
                messages=messages,
                tools=_GRAPH_AGENT_TOOLS,
                model=self.extract_model,
                temperature=0.0,
                max_tokens=900,
                tool_choice="required",
            )
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
            }
            if response.has_tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in response.tool_calls
                ]
            messages.append(assistant_message)

            if not response.has_tool_calls:
                content_preview = (response.content or "").strip().replace("\n", " ")
                finish_reason = response.finish_reason or "stop"
                raise ValueError(
                    "graph_agent_no_tool_calls"
                    + (f": finish_reason={finish_reason}" if finish_reason else "")
                    + (f": content={content_preview[:180]}" if content_preview else "")
                )

            finished = False
            for call in response.tool_calls:
                if status_callback is not None and call.name == "search_graph":
                    await status_callback("searching", "searching existing graph")
                if status_callback is not None and call.name in {"create_entity", "create_fact", "create_relation"}:
                    await status_callback("staging", "staging entities/facts/relations")
                result, finished = self._run_graph_tool(call.name, call.arguments, stage)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            if finished:
                return self._finalize_graph_stage(stage)

        if stage["entities"] or stage["facts"] or stage["relations"]:
            return self._finalize_graph_stage(stage)
        raise ValueError("graph_agent_exceeded_tool_budget")

    def _run_graph_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        stage: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        if name == "search_graph":
            query = str(arguments.get("query", "")).strip()
            limit = max(1, min(32, int(arguments.get("limit", 20) or 20)))
            rows = self._search_graph_candidates(query, limit=limit) if query else []
            return {
                "matches": [
                    {
                        "id": str(row["id"]),
                        "label": str(row["label"]),
                        "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                        "search_score": float(row.get("search_score", 0.0)),
                        "semantic_score": float(row.get("semantic_score", 0.0)),
                        "lexical_score": float(row.get("lexical_score", 0.0)),
                    }
                    for row in rows
                ]
            }, False

        if name == "read_graph_node":
            node_id = str(arguments.get("node_id", "")).strip()
            row = self.registry.get_graph_node(node_id)
            if row is None:
                return {"found": False, "node_id": node_id}, False
            edges = self.registry.get_graph_edges_for_node(node_id, limit=12)
            return {
                "found": True,
                "node": {
                    "id": str(row["id"]),
                    "label": str(row["label"]),
                    "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                },
                "edges": [
                    {
                        "source_id": str(edge["source_id"]),
                        "target_id": str(edge["target_id"]),
                        "relation": str(edge["relation"]),
                        "weight": float(edge["weight"]),
                    }
                    for edge in edges
                ],
            }, False

        if name == "create_entity":
            surface_label = str(arguments.get("surface_label") or arguments.get("label") or "").strip()
            requested_canonical = str(arguments.get("canonical_english_label") or arguments.get("label") or "").strip()
            kind = str(arguments.get("kind", "")).strip() or "entity"
            surface_language = self._detect_language(surface_label) if surface_label else "unknown"
            english_label, source_language, language_confidence, normalization_method = self._canonicalize_english(
                requested_canonical or surface_label
            )
            if not english_label and surface_label:
                english_label, source_language, language_confidence, normalization_method = self._canonicalize_english(surface_label)
            if not english_label:
                return {"ok": False, "error": "english_canonicalization_required"}, False
            if language_confidence < 0.75 or self._normalize_text(surface_label or english_label) in _GENERIC_ENTITY_WORDS:
                return {"ok": False, "error": "ambiguous_or_generic_entity"}, False
            if not surface_label:
                surface_label = english_label
            if not english_label:
                return {"ok": False, "error": "label_required"}, False
            entity_id = str(arguments.get("entity_id") or self._find_existing_entity_id(english_label) or f"entity:{self._slug(english_label)}")
            aliases = [str(item).strip() for item in (arguments.get("aliases") or []) if str(item).strip()]
            stage["entities"][entity_id] = {
                "id": entity_id,
                "name": english_label,
                "surface_label": surface_label,
                "kind": kind,
                "aliases": aliases,
                "source_language": str(arguments.get("source_language") or (surface_language if surface_language != "unknown" else source_language)),
                "language_confidence": float(arguments.get("language_confidence", language_confidence) or language_confidence),
                "normalization_method": normalization_method,
                "ambiguous_language": bool(arguments.get("ambiguous_language", language_confidence < 0.75)),
                "confidence": float(arguments.get("confidence", 0.7) or 0.7),
            }
            return {"ok": True, "entity_id": entity_id}, False

        if name == "create_entities":
            created: list[str] = []
            for item in arguments.get("items") or []:
                result, _ = self._run_graph_tool("create_entity", item, stage)
                if result.get("ok") and result.get("entity_id"):
                    created.append(str(result["entity_id"]))
            return {"ok": True, "entity_ids": created}, False

        if name == "create_fact":
            surface_statement = str(arguments.get("surface_statement") or arguments.get("statement") or "").strip()
            requested_english = str(arguments.get("statement_english") or arguments.get("statement") or "").strip()
            surface_language = self._detect_language(surface_statement) if surface_statement else "unknown"
            statement, source_language, language_confidence, normalization_method = self._canonicalize_english(
                requested_english or surface_statement
            )
            if not statement and surface_statement:
                statement, source_language, language_confidence, normalization_method = self._canonicalize_english(surface_statement)
            if not statement:
                return {"ok": False, "error": "statement_required"}, False
            if language_confidence < 0.75:
                return {"ok": False, "error": "ambiguous_fact_language"}, False
            fact_id = str(arguments.get("fact_id") or f"fact:{self._slug(statement)}")
            stage["facts"][fact_id] = {
                "id": fact_id,
                "statement": statement,
                "surface_statement": surface_statement or statement,
                "subject": str(arguments.get("subject_id") or ""),
                "source_language": str(arguments.get("source_language") or (surface_language if surface_language != "unknown" else source_language)),
                "language_confidence": float(arguments.get("language_confidence", language_confidence) or language_confidence),
                "normalization_method": normalization_method,
                "ambiguous_language": bool(arguments.get("ambiguous_language", language_confidence < 0.75)),
                "confidence": float(arguments.get("confidence", 0.8) or 0.8),
                "supersedes": [str(item).strip() for item in (arguments.get("supersedes") or []) if str(item).strip()],
            }
            return {"ok": True, "fact_id": fact_id}, False

        if name == "create_facts":
            created: list[str] = []
            for item in arguments.get("items") or []:
                result, _ = self._run_graph_tool("create_fact", item, stage)
                if result.get("ok") and result.get("fact_id"):
                    created.append(str(result["fact_id"]))
            return {"ok": True, "fact_ids": created}, False

        if name == "create_relation":
            source_id = str(arguments.get("source_id", "")).strip()
            target_id = str(arguments.get("target_id", "")).strip()
            relation, relation_conf = self._normalize_relation(str(arguments.get("relation", "")).strip())
            if not source_id or not target_id or not relation:
                return {"ok": False, "error": "source_target_relation_required"}, False
            if relation_conf < 0.75:
                return {"ok": False, "error": "relation_not_allowed"}, False
            relation_item = {
                "source": source_id,
                "target": target_id,
                "type": relation,
                "confidence": float(arguments.get("confidence", relation_conf) or relation_conf),
            }
            if relation_item not in stage["relations"]:
                stage["relations"].append(relation_item)
            return {"ok": True}, False

        if name == "create_relations":
            created = 0
            for item in arguments.get("items") or []:
                result, _ = self._run_graph_tool("create_relation", item, stage)
                if result.get("ok"):
                    created += 1
            return {"ok": True, "relations": created}, False

        if name == "finish_graph_plan":
            stage["reason"] = str(arguments.get("reason", "")).strip()
            if arguments.get("summary"):
                stage["summary"] = str(arguments["summary"])
            return {
                "ok": True,
                "reason": stage["reason"],
                "entities": len(stage["entities"]),
                "facts": len(stage["facts"]),
                "relations": len(stage["relations"]),
            }, True

        return {"ok": False, "error": f"unknown_tool:{name}"}, False

    def _finalize_graph_stage(self, stage: dict[str, Any]) -> dict[str, Any] | None:
        entities = list(stage["entities"].values())
        facts = list(stage["facts"].values())
        relations = list(stage["relations"])
        if not entities and not facts and not relations:
            return None
        return {
            "summary": str(stage.get("summary") or ""),
            "entities": entities[:12],
            "facts": facts[:8],
            "relations": relations[:16],
        }

    def _persist_graph(self, episode: EpisodeRecord, summary: str, extraction: dict[str, Any]) -> None:
        episode_node = f"episode:{episode.episode_id}"
        node_rows: list[tuple[str, str, dict[str, Any]]] = [
            (
                episode_node,
                episode.turn_id,
                {
                    "kind": "episode",
                    "summary": summary,
                    "session_key": episode.session_key,
                    "episode_id": episode.episode_id,
                    "turn_id": episode.turn_id,
                    "timestamp": episode.timestamp,
                    "source": "llm_graph_agent",
                },
            )
        ]
        alias_rows_by_entity: dict[str, list[dict[str, Any]]] = {}
        edge_rows: list[tuple[str, str, str, float, dict[str, Any]]] = []

        entities = extraction.get("entities") or []
        facts = extraction.get("facts") or []
        relations = extraction.get("relations") or []

        for entity in entities:
            entity_id = str(entity.get("id") or f"entity:{self._slug(entity.get('name', 'unknown'))}")
            label = str(entity.get("name") or entity_id)
            aliases = self._build_alias_rows(
                label,
                list(entity.get("aliases") or []),
                str(entity.get("surface_label") or label),
            )
            metadata = {
                "kind": entity.get("kind", "entity"),
                "aliases": [item["alias_text"] for item in aliases],
                "canonical_name": label,
                "source_language": entity.get("source_language", "en"),
                "language_confidence": entity.get("language_confidence", 1.0),
                "normalization_method": entity.get("normalization_method", "exact"),
                "confidence": entity.get("confidence", 0.7),
                "provenance_episode": episode.episode_id,
                "source": "llm_graph_agent",
            }
            node_rows.append((entity_id, label, metadata, 3))
            alias_rows_by_entity[entity_id] = aliases
            edge_rows.append(
                (
                    episode_node,
                    entity_id,
                    "mentions",
                    float(entity.get("confidence", 0.7)),
                    {"episode_id": episode.episode_id, "source": "entity"},
                )
            )

        for fact in facts:
            fact_id = str(fact.get("id") or f"fact:{self._slug(fact.get('statement', 'fact'))}")
            statement = str(fact.get("statement") or summary)
            node_rows.append(
                (
                    fact_id,
                    statement[:180],
                    {
                        "kind": "fact",
                        "statement": statement,
                        "canonical_statement_en": statement,
                        "surface_statement": fact.get("surface_statement", statement),
                        "source_language": fact.get("source_language", "en"),
                        "language_confidence": fact.get("language_confidence", 1.0),
                        "normalization_method": fact.get("normalization_method", "exact"),
                        "confidence": fact.get("confidence", 0.8),
                        "provenance_episode": episode.episode_id,
                        "supersedes": fact.get("supersedes", []),
                        "source": "llm_graph_agent",
                    },
                    3,
                )
            )
            subject = str(fact.get("subject") or episode_node)
            edge_rows.append(
                (
                    subject,
                    fact_id,
                    "decided",
                    float(fact.get("confidence", 0.8)),
                    {"episode_id": episode.episode_id},
                )
            )
            edge_rows.append(
                (
                    episode_node,
                    fact_id,
                    "mentions",
                    float(fact.get("confidence", 0.8)),
                    {"episode_id": episode.episode_id},
                )
            )
            for superseded in fact.get("supersedes", []):
                edge_rows.append(
                    (
                        fact_id,
                        str(superseded),
                        "supersedes",
                        1.0,
                        {"episode_id": episode.episode_id, "superseded": True},
                    )
                )

        for relation in relations:
            edge_rows.append(
                (
                    str(relation.get("source") or episode_node),
                    str(relation.get("target") or episode_node),
                    str(relation.get("type") or "mentions"),
                    float(relation.get("confidence", 0.75)),
                    {"episode_id": episode.episode_id, "source": "relation"},
                )
            )

        try:
            logger.debug(
                "Persisting graph: {} nodes, {} edges,  entities with aliases",
                len(node_rows),
                len(edge_rows),
                len(alias_rows_by_entity),
            )
            self.registry.bulk_upsert_graph_nodes(node_rows)
            self.registry.bulk_replace_graph_aliases(alias_rows_by_entity)
            self.registry.bulk_upsert_graph_edges(edge_rows)

            if self.semantic_embedder:
                for node_id, label, metadata, *_ in node_rows:
                    try:
                        vector = self.semantic_embedder.embed(label)
                        self.registry.upsert_node_embedding(node_id, vector)
                    except Exception as emb_exc:
                        logger.warning("Failed to embed node {}: {}", node_id, emb_exc)
        except Exception as exc:
            logger.error(
                "Graph persistence failed: {} | extraction keys: {} | entities: {} | facts: {} | relations: {}",
                exc,
                list(extraction.keys()),
                len(entities),
                len(facts),
                len(relations),
            )
            raise

    def _slug(self, value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]

    def retrieve(self, query: str, limit: int = 5) -> list[RetrievedMemory]:
        rows = self.registry.query_graph(query, limit=limit)
        results: list[RetrievedMemory] = []
        for row in rows:
            node_meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            edge_meta = json.loads(row["edge_metadata"]) if row["edge_metadata"] else {}
            relation = row["relation"] or "node_match"
            snippet = row["label"]
            if row["target_id"]:
                snippet = f"{row['label']} --{relation}--> {row['target_id']}"
            results.append(
                RetrievedMemory(
                    artifact_id=row["id"],
                    store="graph",
                    score=float(row["weight"] or 0.5),
                    snippet=snippet,
                    reason=f"Graph {relation} match",
                    metadata={**node_meta, **edge_meta, "relation": relation},
                )
            )
        return results


class Neo4jGraphBackend(LocalGraphBackend):
    """Optional Neo4j sink mirroring the local graph model."""

    def __init__(
        self,
        workspace: Path,
        registry: MemoryRegistry,
        uri: str,
        username: str,
        password: str,
        **kwargs: Any,
    ):
        super().__init__(workspace, registry, **kwargs)
        self._driver = None
        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(uri, auth=(username, password))
        except Exception as exc:
            logger.warning("Neo4j graph backend unavailable, falling back to local graph only: {}", exc)

    def healthcheck(self) -> bool:
        return self._driver is not None

    async def ingest_episode_async(self, episode: EpisodeRecord) -> None:
        await super().ingest_episode_async(episode)
        if not self.healthcheck():
            return
        assert self._driver is not None
        rows = self.registry.query_graph(episode.turn_id, limit=64)
        try:
            with self._driver.session() as session:
                for row in rows:
                    session.run(
                        """
                        MERGE (s:Node {id: $source_id})
                        SET s.label = $source_label
                        WITH s
                        MERGE (t:Node {id: $target_id})
                        SET t.label = $target_label
                        WITH s, t
                        MERGE (s)-[r:RELATED {type: $relation}]->(t)
                        SET r.weight = $weight
                        """,
                        source_id=row["id"],
                        source_label=row["label"],
                        target_id=row["target_id"] or row["id"],
                        target_label=row["target_id"] or row["label"],
                        relation=row["relation"] or "node_match",
                        weight=float(row["weight"] or 0.5),
                    )
        except Exception as exc:
            logger.warning("Neo4j ingest failed for {}: {}", episode.episode_id, exc)

    def sync_node(self, node_id: str) -> str | None:
        if not self.healthcheck():
            return None
        row = self.registry.get_graph_node(node_id)
        if row is None:
            return self.delete_node(node_id)
        assert self._driver is not None
        try:
            with self._driver.session() as session:
                session.run(
                    """
                    MERGE (n:Node {id: $id})
                    SET n.label = $label,
                        n.metadata_json = $metadata_json
                    """,
                    id=row["id"],
                    label=row["label"],
                    metadata_json=row["metadata_json"],
                )
            return None
        except Exception as exc:
            logger.warning("Neo4j node sync failed for {}: {}", node_id, exc)
            return str(exc)

    def sync_edge(self, source_id: str, target_id: str, relation: str) -> str | None:
        if not self.healthcheck():
            return None
        row = self.registry.get_graph_edge(source_id, target_id, relation)
        if row is None:
            return self.delete_edge(source_id, target_id, relation)
        source = self.registry.get_graph_node(source_id)
        target = self.registry.get_graph_node(target_id)
        if source is None or target is None:
            return "source_or_target_missing"
        assert self._driver is not None
        try:
            with self._driver.session() as session:
                session.run(
                    """
                    MERGE (s:Node {id: $source_id})
                    SET s.label = $source_label
                    WITH s
                    MERGE (t:Node {id: $target_id})
                    SET t.label = $target_label
                    WITH s, t
                    MERGE (s)-[r:RELATED {type: $relation}]->(t)
                    SET r.weight = $weight,
                        r.metadata_json = $metadata_json
                    """,
                    source_id=source["id"],
                    source_label=source["label"],
                    target_id=target["id"],
                    target_label=target["label"],
                    relation=row["relation"],
                    weight=float(row["weight"] or 0.0),
                    metadata_json=row["metadata_json"],
                )
            return None
        except Exception as exc:
            logger.warning("Neo4j edge sync failed for {}-{}-{}: {}", source_id, relation, target_id, exc)
            return str(exc)

    def delete_node(self, node_id: str) -> str | None:
        if not self.healthcheck():
            return None
        assert self._driver is not None
        try:
            with self._driver.session() as session:
                session.run("MATCH (n:Node {id: $id}) DETACH DELETE n", id=node_id)
            return None
        except Exception as exc:
            logger.warning("Neo4j node delete failed for {}: {}", node_id, exc)
            return str(exc)

    def delete_edge(self, source_id: str, target_id: str, relation: str) -> str | None:
        if not self.healthcheck():
            return None
        assert self._driver is not None
        try:
            with self._driver.session() as session:
                session.run(
                    """
                    MATCH (s:Node {id: $source_id})-[r:RELATED {type: $relation}]->(t:Node {id: $target_id})
                    DELETE r
                    """,
                    source_id=source_id,
                    target_id=target_id,
                    relation=relation,
                )
            return None
        except Exception as exc:
            logger.warning("Neo4j edge delete failed for {}-{}-{}: {}", source_id, relation, target_id, exc)
            return str(exc)
