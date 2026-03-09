"""Graph memory backends and extraction pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

from fagent.memory.policy import MemoryPolicy
from fagent.memory.registry import MemoryRegistry
from fagent.memory.types import EpisodeRecord, GraphExtractionJob, RetrievedMemory
from fagent.prompts import PromptLoader
from fagent.providers.base import LLMProvider


class LocalGraphBackend:
    """SQLite-backed graph memory with optional LLM extraction and normalization."""

    _STOPWORDS = {
        "the", "and", "for", "with", "that", "this", "from", "into", "about", "what",
        "как", "что", "это", "для", "или", "ещё", "еще", "чтобы", "после", "пока",
    }

    def __init__(
        self,
        workspace: Path,
        registry: MemoryRegistry,
        *,
        provider: LLMProvider | None = None,
        extract_model: str | None = None,
        normalize_model: str | None = None,
        prompt_loader: PromptLoader | None = None,
    ):
        self.workspace = workspace
        self.registry = registry
        self.policy = MemoryPolicy()
        self.provider = provider
        self.extract_model = extract_model
        self.normalize_model = normalize_model
        self.prompt_loader = prompt_loader or PromptLoader.from_package()

    def healthcheck(self) -> bool:
        return True

    async def ingest_episode_async(self, episode: EpisodeRecord) -> None:
        summary = self.policy.build_summary(episode)
        extractor_prompt = self.prompt_loader.load("system/memory-extractor.md")
        normalizer_prompt = self.prompt_loader.load("system/graph-normalizer.md")
        job = GraphExtractionJob(
            job_id=f"graph-{episode.episode_id}",
            episode_id=episode.episode_id,
            summary=summary,
            status="running",
            attempts=(self.registry.get_graph_job(episode.episode_id).attempts + 1) if self.registry.get_graph_job(episode.episode_id) else 1,
            prompt_version=f"{extractor_prompt.version}:{normalizer_prompt.version}",
            model_role="graph_extract",
        )
        self.registry.upsert_graph_job(job)
        try:
            extraction = await self._extract_with_llm(episode, summary, extractor_prompt.text, normalizer_prompt.text)
            if extraction is None:
                extraction = self._extract_fallback(episode, summary)
            self._persist_graph(episode, summary, extraction)
            job.status = "done"
            self.registry.upsert_graph_job(job)
        except Exception as exc:
            logger.warning("Graph extraction failed for {}: {}", episode.episode_id, exc)
            job.status = "retry"
            self.registry.upsert_graph_job(job)
            self._persist_graph(episode, summary, self._extract_fallback(episode, summary))

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
        normalizer_prompt: str,
    ) -> dict[str, Any] | None:
        if self.provider is None or not self.extract_model:
            return None
        response = await self.provider.chat(
            messages=[
                {"role": "system", "content": extractor_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Episode ID: {episode.episode_id}\n"
                        f"Session: {episode.session_key}\n"
                        f"Summary: {summary}\n\n"
                        f"Episode:\n{episode.content}\n\n"
                        "Return JSON only."
                    ),
                },
            ],
            model=self.extract_model,
            temperature=0.0,
            max_tokens=1200,
        )
        if not response.content:
            return None
        data = self._extract_json(response.content)
        if self.provider is None or not self.normalize_model:
            return data
        normalized = await self.provider.chat(
            messages=[
                {"role": "system", "content": normalizer_prompt},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
            ],
            model=self.normalize_model,
            temperature=0.0,
            max_tokens=1200,
        )
        return self._extract_json(normalized.content) if normalized.content else data

    def _extract_json(self, content: str) -> dict[str, Any]:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            raise ValueError("No JSON object found in graph extraction response")
        return json.loads(match.group(0))

    def _extract_fallback(self, episode: EpisodeRecord, summary: str) -> dict[str, Any]:
        text = f"{episode.user_text}\n{episode.assistant_text}"
        entities: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []

        for raw in re.findall(r"[A-Za-zА-Яа-я0-9_.-]{3,}", text):
            token = raw.strip(".,:;!?()[]{}\"'").lower()
            if token in self._STOPWORDS or token.isdigit():
                continue
            entities.append(
                {
                    "id": f"entity:{token}",
                    "name": token,
                    "kind": "concept",
                    "aliases": [raw],
                    "confidence": 0.45,
                }
            )
        seen = set()
        deduped_entities = []
        for item in entities:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            deduped_entities.append(item)

        if deduped_entities:
            primary = deduped_entities[0]
            facts.append(
                {
                    "id": f"fact:{episode.episode_id}:summary",
                    "statement": summary,
                    "subject": primary["id"],
                    "confidence": 0.55,
                    "supersedes": [],
                }
            )
        for left, right in zip(deduped_entities, deduped_entities[1:]):
            relations.append(
                {
                    "source": left["id"],
                    "target": right["id"],
                    "type": "relates_to",
                    "confidence": 0.4,
                }
            )
        return {
            "summary": summary,
            "entities": deduped_entities[:12],
            "facts": facts,
            "relations": relations[:24],
        }

    def _persist_graph(self, episode: EpisodeRecord, summary: str, extraction: dict[str, Any]) -> None:
        episode_node = f"episode:{episode.episode_id}"
        self.registry.upsert_graph_node(
            episode_node,
            label=episode.turn_id,
            metadata={
                "kind": "episode",
                "summary": summary,
                "session_key": episode.session_key,
                "episode_id": episode.episode_id,
                "turn_id": episode.turn_id,
                "timestamp": episode.timestamp,
            },
        )
        entities = extraction.get("entities") or []
        facts = extraction.get("facts") or []
        relations = extraction.get("relations") or []
        for entity in entities:
            entity_id = str(entity.get("id") or f"entity:{self._slug(entity.get('name', 'unknown'))}")
            label = str(entity.get("name") or entity_id)
            metadata = {
                "kind": entity.get("kind", "entity"),
                "aliases": entity.get("aliases", []),
                "confidence": entity.get("confidence", 0.5),
                "provenance_episode": episode.episode_id,
            }
            self.registry.upsert_graph_node(entity_id, label=label, metadata=metadata)
            self.registry.upsert_graph_edge(
                episode_node,
                entity_id,
                relation="mentions",
                weight=float(entity.get("confidence", 0.5)),
                metadata={"episode_id": episode.episode_id, "source": "entity"},
            )
        for fact in facts:
            fact_id = str(fact.get("id") or f"fact:{episode.episode_id}:{self._slug(fact.get('statement', 'fact'))}")
            statement = str(fact.get("statement") or summary)
            self.registry.upsert_graph_node(
                fact_id,
                label=statement[:180],
                metadata={
                    "kind": "fact",
                    "statement": statement,
                    "confidence": fact.get("confidence", 0.6),
                    "provenance_episode": episode.episode_id,
                    "supersedes": fact.get("supersedes", []),
                },
            )
            subject = str(fact.get("subject") or episode_node)
            self.registry.upsert_graph_edge(
                subject,
                fact_id,
                relation="decided",
                weight=float(fact.get("confidence", 0.6)),
                metadata={"episode_id": episode.episode_id},
            )
            self.registry.upsert_graph_edge(
                episode_node,
                fact_id,
                relation="mentions",
                weight=float(fact.get("confidence", 0.6)),
                metadata={"episode_id": episode.episode_id},
            )
            for superseded in fact.get("supersedes", []):
                self.registry.upsert_graph_edge(
                    fact_id,
                    str(superseded),
                    relation="supersedes",
                    weight=1.0,
                    metadata={"episode_id": episode.episode_id, "superseded": True},
                )
        for relation in relations:
            self.registry.upsert_graph_edge(
                str(relation.get("source") or episode_node),
                str(relation.get("target") or episode_node),
                relation=str(relation.get("type") or "relates_to"),
                weight=float(relation.get("confidence", 0.5)),
                metadata={"episode_id": episode.episode_id, "source": "relation"},
            )

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
