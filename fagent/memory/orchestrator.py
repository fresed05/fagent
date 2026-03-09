"""Main orchestration layer for memory retrieval and ingestion."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
import json

from loguru import logger

from fagent.memory.file_store import FileMemoryStore
from fagent.memory.graph import LocalGraphBackend, Neo4jGraphBackend
from fagent.memory.policy import MemoryPolicy
from fagent.memory.registry import MemoryRegistry
from fagent.memory.router import MemoryRouter
from fagent.memory.shadow import ShadowContextBuilder
from fagent.memory.types import (
    EpisodeRecord,
    ExperiencePattern,
    MemoryArtifact,
    MemorySearchRequestV2,
    RetrievedMemory,
    SessionSummaryArtifact,
    ShadowBrief,
    TaskNode,
    WorkflowStateArtifact,
)
from fagent.memory.vector import VectorMemoryBackend
from fagent.prompts import PromptLoader

if TYPE_CHECKING:
    from fagent.config.schema import Config, MemoryConfig
    from fagent.providers.base import LLMProvider
    from fagent.session.manager import Session


class MemoryOrchestrator:
    """Coordinates file, vector, graph, and shadow-context memory layers."""

    def __init__(
        self,
        workspace: Path,
        provider: "LLMProvider | None" = None,
        config: "MemoryConfig | None" = None,
        model: str | None = None,
        app_config: "Config | None" = None,
    ):
        from fagent.config.schema import MemoryConfig

        self.workspace = workspace
        self.provider = provider
        self.config = config or MemoryConfig()
        self.model = model
        self.registry = MemoryRegistry(workspace)
        self.policy = MemoryPolicy()
        self.prompts = PromptLoader.from_package()
        self.app_config = app_config
        self.file_store = FileMemoryStore(workspace)
        embedding_role = app_config.resolve_model_role("embeddings") if app_config else None
        shadow_role = app_config.resolve_model_role("shadow", model) if app_config else None
        self.vector_backend = VectorMemoryBackend(
            workspace,
            collection=self.config.vector.collection,
            embedding_model=(embedding_role.model if embedding_role else self.config.vector.embedding_model),
            embedding_api_base=(embedding_role.api_base if embedding_role else self.config.vector.embedding_api_base),
            embedding_api_key=(embedding_role.api_key if embedding_role else self.config.vector.embedding_api_key),
            embedding_dimensions=((embedding_role.dimensions or 0) if embedding_role else self.config.vector.embedding_dimensions),
            embedding_extra_headers=(embedding_role.extra_headers if embedding_role else self.config.vector.embedding_extra_headers),
            batch_size=self.config.vector.batch_size,
            request_timeout_s=((embedding_role.timeout_s) if embedding_role else self.config.vector.request_timeout_s),
            cache_ttl_s=self.config.vector.cache_ttl_s,
            registry=self.registry,
        )
        self.graph_backend = self._build_graph_backend(workspace)
        self.router = MemoryRouter(
            provider=provider,
            model=(shadow_role.model if shadow_role else None),
            default_strategy=self.config.router.default_strategy,
            raw_evidence_escalation=self.config.router.raw_evidence_escalation,
        )
        self.shadow = ShadowContextBuilder(
            backends=[
                ("file", self.file_store),
                ("vector", self.vector_backend),
                ("graph", self.graph_backend),
            ],
            provider=provider,
            fast_model=(shadow_role.model if shadow_role and shadow_role.model else self.config.shadow_context.fast_model or model),
            max_tokens=self.config.shadow_context.max_tokens,
            prompt_loader=self.prompts,
        )
        self._tasks: set[asyncio.Task] = set()

    def _build_graph_backend(self, workspace: Path):
        graph_extract_model = None
        graph_normalize_model = None
        if self.app_config:
            graph_extract_model = self.app_config.resolve_model_role("graph_extract", self.model).model
            graph_normalize_model = self.app_config.resolve_model_role("graph_normalize", self.model).model
        if not self.config.graph.enabled:
            return LocalGraphBackend(
                workspace,
                self.registry,
                provider=self.provider,
                extract_model=graph_extract_model,
                normalize_model=graph_normalize_model,
                prompt_loader=self.prompts,
            )
        if self.config.graph.backend == "graphiti-neo4j" and self.config.graph.uri:
            return Neo4jGraphBackend(
                workspace,
                self.registry,
                uri=self.config.graph.uri,
                username=self.config.graph.username,
                password=self.config.graph.password,
                provider=self.provider,
                extract_model=graph_extract_model,
                normalize_model=graph_normalize_model,
                prompt_loader=self.prompts,
            )
        return LocalGraphBackend(
            workspace,
            self.registry,
            provider=self.provider,
            extract_model=graph_extract_model,
            normalize_model=graph_normalize_model,
            prompt_loader=self.prompts,
        )

    async def prepare_shadow_context(
        self,
        user_query: str,
        session_key: str,
        channel_context: dict[str, str],
    ) -> ShadowBrief | None:
        if not self.config.enabled or not self.config.shadow_context.enabled:
            return None
        route = await self.router.route(
            user_query,
            session_key,
            active_task_state=self.get_task_state_summary(session_key),
            recent_workflow_state=self.get_recent_workflow_state(session_key),
        )
        brief = await self.shadow.build(user_query, session_key, channel_context)
        if brief is not None:
            brief.retrieval_strategy = f"router:{route.intent}:{route.strategy}"
        return brief

    def build_episode(
        self,
        session_key: str,
        turn_id: str,
        channel: str,
        chat_id: str,
        saved_entries: list[dict],
    ) -> EpisodeRecord | None:
        if not channel and ":" in session_key:
            channel, chat_id = session_key.split(":", 1)
        user_text = ""
        assistant_text = ""
        tools: list[str] = []
        timestamp = None
        source_path = str(self.workspace / "sessions")
        for entry in saved_entries:
            role = entry.get("role")
            content = entry.get("content")
            if role == "user" and isinstance(content, str):
                user_text = content
                timestamp = entry.get("timestamp", timestamp)
            elif role == "assistant" and isinstance(content, str):
                assistant_text = content
                timestamp = entry.get("timestamp", timestamp)
            elif role == "assistant" and entry.get("tool_calls"):
                tools.extend(call["function"]["name"] for call in entry["tool_calls"])
            elif role == "tool":
                tools.append(entry.get("name", "tool"))
        if not user_text and not assistant_text:
            return None
        episode_id = hashlib.sha1(f"{session_key}:{turn_id}".encode("utf-8")).hexdigest()[:16]
        topic_tags = self.policy.extract_topic_tags(f"{user_text}\n{assistant_text}")
        return EpisodeRecord(
            episode_id=episode_id,
            session_key=session_key,
            turn_id=turn_id,
            channel=channel,
            chat_id=chat_id,
            user_text=user_text,
            assistant_text=assistant_text,
            tool_trace=tools,
            timestamp=timestamp or "",
            metadata={"topic_tags": topic_tags, "source_path": source_path},
        )

    async def enqueue_post_turn_ingest(self, episode: EpisodeRecord | None) -> None:
        if not self.config.enabled or episode is None:
            return
        if self.registry.get_job_status(episode.episode_id) == "done":
            return
        if not self.config.ingest.async_enabled:
            await self.ingest_episode(episode)
            return

        async def _runner() -> None:
            try:
                await self.ingest_episode(episode)
            finally:
                task = asyncio.current_task()
                if task is not None:
                    self._tasks.discard(task)

        task = asyncio.create_task(_runner())
        self._tasks.add(task)

    async def ingest_episode(self, episode: EpisodeRecord) -> None:
        if self.registry.get_job_status(episode.episode_id) == "done":
            return
        self.registry.set_job_status(episode.episode_id, "running")
        try:
            summary = self.policy.build_summary(episode)
            episode_artifact = MemoryArtifact(
                id=episode.episode_id,
                type="session_turn",
                content=episode.content,
                summary=summary,
                metadata={
                    "session_key": episode.session_key,
                    "turn_id": episode.turn_id,
                    "chat_id": episode.chat_id,
                    "channel": episode.channel,
                    "topic_tags": episode.metadata.get("topic_tags", []),
                },
                source_ref=episode.metadata.get("source_path", ""),
                created_at=episode.timestamp,
            )
            self.registry.upsert_artifact(episode_artifact)
            file_artifacts: list[MemoryArtifact] = []
            if not self.registry.get_artifact(f"{episode.episode_id}:history"):
                file_artifacts = self.file_store.ingest_episode(episode, summary=summary)
                for artifact in file_artifacts:
                    self.registry.upsert_artifact(artifact)
            else:
                for suffix in ("history", "daily", "memory"):
                    artifact = self.registry.get_artifact(f"{episode.episode_id}:{suffix}")
                    if artifact is not None:
                        file_artifacts.append(artifact)

            self.vector_backend.ingest_artifacts(file_artifacts)
            self.vector_backend.ingest_episode(episode)
            await self.graph_backend.ingest_episode_async(episode)
            self.registry.set_job_status(episode.episode_id, "done")
        except Exception as exc:
            self.record_experience_event(
                category="environment_constraint",
                session_key=episode.session_key,
                trigger_text=f"ingest failed: {exc}",
                recovery_text="retry ingest later",
                metadata={"episode_id": episode.episode_id},
            )
            self.registry.set_job_status(episode.episode_id, "retry", error=str(exc))
            logger.exception("Memory ingest failed for {}", episode.episode_id)

    async def consolidate_session(self, session: "Session") -> bool:
        """Best-effort compatibility hook for old consolidation paths."""
        try:
            if not session.messages:
                return True
            last_turn = session.metadata.get("turn_seq", 0)
            turn_id = f"turn-{last_turn:06d}"
            saved = [msg for msg in session.messages if msg.get("turn_id") == turn_id]
            episode = self.build_episode(session.key, turn_id, "", "", saved)
            if episode:
                await self.enqueue_post_turn_ingest(episode)
            return True
        except Exception:
            logger.exception("Session consolidation failed")
            return False

    async def backfill_sessions(self, sessions: list["Session"]) -> int:
        count = 0
        for session in sessions:
            turn_ids = sorted({msg.get("turn_id") for msg in session.messages if msg.get("turn_id")})
            for turn_id in turn_ids:
                saved = [msg for msg in session.messages if msg.get("turn_id") == turn_id]
                episode = self.build_episode(session.key, turn_id, "", "", saved)
                if episode is None:
                    continue
                await self.ingest_episode(episode)
                count += 1
        return count

    def search(
        self,
        query: str,
        *,
        stores: list[str] | None = None,
        artifact_types: list[str] | None = None,
        top_k: int = 10,
        session_scope: str | None = None,
        time_range: dict[str, str] | None = None,
    ) -> list[RetrievedMemory]:
        selected = set(stores or ["file", "vector", "graph"])
        results: list[RetrievedMemory] = []
        if "file" in selected:
            results.extend(self.file_store.retrieve(query, limit=top_k))
        try:
            if "vector" in selected:
                results.extend(self.vector_backend.retrieve(query, limit=top_k))
        except Exception as exc:
            logger.warning("Vector retrieval failed for query '{}': {}", query, exc)
        try:
            if "graph" in selected:
                results.extend(self.graph_backend.retrieve(query, limit=top_k))
        except Exception as exc:
            logger.warning("Graph retrieval failed for query '{}': {}", query, exc)
        if session_scope:
            results = [item for item in results if item.metadata.get("session_key") in ("", session_scope)]
        if artifact_types:
            results = [
                item for item in results
                if item.metadata.get("artifact_type") in artifact_types
                or item.metadata.get("kind") in artifact_types
                or (item.store == "file" and "daily_note" in artifact_types and item.metadata.get("path", "").endswith(".md"))
            ]
        if time_range and (start := time_range.get("start")):
            end = time_range.get("end", "9999-12-31T23:59:59")
            filtered: list[RetrievedMemory] = []
            for item in results:
                ts = str(item.metadata.get("timestamp") or item.metadata.get("created_at") or "")
                if start <= ts <= end:
                    filtered.append(item)
            results = filtered
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def _dedupe_results(self, items: list[RetrievedMemory], limit: int) -> list[RetrievedMemory]:
        merged: dict[str, RetrievedMemory] = {}
        for item in items:
            existing = merged.get(item.artifact_id)
            if existing is None or item.score > existing.score:
                merged[item.artifact_id] = item
        ranked = sorted(merged.values(), key=lambda item: item.score, reverse=True)
        return ranked[:limit]

    def _workflow_snapshot_results(self, session_key: str, limit: int) -> list[RetrievedMemory]:
        rows = self.registry.latest_workflow_snapshots(session_key, limit=limit)
        results: list[RetrievedMemory] = []
        for row in rows:
            blockers = json.loads(row["open_blockers_json"])
            citations = json.loads(row["citations_json"])
            results.append(
                RetrievedMemory(
                    artifact_id=f"workflow:{row['snapshot_id']}",
                    store="workflow",
                    score=0.78,
                    snippet=str(row["current_state"])[:320],
                    reason="Recent workflow snapshot",
                    metadata={
                        "artifact_type": "workflow_state",
                        "session_key": row["session_key"],
                        "turn_id": row["turn_id"],
                        "timestamp": row["created_at"],
                        "open_blockers": blockers,
                        "citations": citations,
                    },
                )
            )
        return results

    def _task_graph_results(self, session_key: str, query: str, limit: int) -> list[RetrievedMemory]:
        rows = self.registry.query_task_nodes(session_key, query, limit=limit)
        results: list[RetrievedMemory] = []
        for row in rows:
            results.append(
                RetrievedMemory(
                    artifact_id=str(row["node_id"]),
                    store="task_graph",
                    score=0.82 if row["node_type"] in {"goal", "decision", "blocker"} else 0.74,
                    snippet=f"{row['node_type']}: {row['title']} | {row['summary']}"[:320],
                    reason=f"Task graph {row['node_type']} match",
                    metadata={
                        "artifact_type": "task_state" if row["node_type"] == "goal" else "task_step",
                        "session_key": row["session_key"],
                        "status": row["status"],
                        "node_type": row["node_type"],
                        "source_artifact_id": row["source_artifact_id"],
                        "timestamp": row["created_at"],
                        "task_id": row["task_id"],
                    },
                )
            )
        return results

    def _experience_results(self, session_key: str | None, query: str, limit: int) -> list[RetrievedMemory]:
        query_lower = query.lower()
        patterns = self.registry.list_experience_patterns(session_key=session_key, limit=max(limit * 2, limit))
        results: list[RetrievedMemory] = []
        for pattern in patterns:
            haystack = f"{pattern.category}\n{pattern.trigger}\n{pattern.recovery}".lower()
            if query_lower not in haystack and not any(token in haystack for token in query_lower.split() if len(token) > 3):
                continue
            results.append(self._experience_to_result(pattern, session_key))
            if len(results) >= limit:
                break
        return results

    def _experience_to_result(self, pattern: ExperiencePattern, session_key: str | None) -> RetrievedMemory:
        return RetrievedMemory(
            artifact_id=f"experience:{pattern.pattern_key}",
            store="experience",
            score=min(0.92, 0.65 + 0.08 * pattern.evidence_count),
            snippet=f"{pattern.category}: {pattern.trigger} -> {pattern.recovery}"[:320],
            reason="Repeated operational pattern",
            metadata={
                "artifact_type": "experience_pattern",
                "session_key": session_key or "",
                "category": pattern.category,
                "evidence_count": pattern.evidence_count,
                "timestamp": pattern.last_seen_at,
            },
        )

    def _latest_session_summary_result(self, session_key: str) -> list[RetrievedMemory]:
        rollup = self.registry.latest_session_rollup(session_key)
        if rollup is None:
            return []
        return [
            RetrievedMemory(
                artifact_id=f"session_summary:{rollup['summary_id']}",
                store="summary",
                score=0.88,
                snippet=str(rollup["summary"])[:320],
                reason="Latest archived session summary",
                metadata={
                    "artifact_type": "session_summary",
                    "session_key": rollup["session_key"],
                    "timestamp": rollup["created_at"],
                    "covered_turns": json.loads(rollup["covered_turns_json"]),
                },
            )
        ]

    async def search_v2(
        self,
        query: str,
        *,
        strategy: str | None = None,
        stores: list[str] | None = None,
        artifact_types: list[str] | None = None,
        top_k: int | None = None,
        session_scope: str | None = None,
        time_range: dict[str, str] | None = None,
        allow_raw_escalation: bool | None = None,
    ) -> dict[str, object]:
        request = await self.router.build_request(
            query,
            session_scope or "",
            strategy=strategy,
            active_task_state=self.get_task_state_summary(session_scope or ""),
            recent_workflow_state=self.get_recent_workflow_state(session_scope or ""),
        )
        selected_stores = stores or request.stores
        selected_types = artifact_types or request.artifact_types
        limit = top_k or request.stores.__len__() or self.config.search_v2.default_top_k
        results: list[RetrievedMemory] = []

        if request.intent in {"continuity", "broad_synthesis"} and session_scope:
            results.extend(self._latest_session_summary_result(session_scope))
        if request.intent in {"continuity", "workflow_recall", "relationship_recall"} and session_scope:
            results.extend(self._task_graph_results(session_scope, query, limit))
        if request.intent == "workflow_recall" and session_scope:
            results.extend(self._workflow_snapshot_results(session_scope, limit))
            results.extend(self._experience_results(session_scope, query, limit))
        elif request.intent in {"factual_recall", "preference_recall"}:
            results.extend(self._experience_results(session_scope, query, max(2, limit // 2)))

        results.extend(self.search(
            query,
            stores=selected_stores,
            artifact_types=selected_types,
            top_k=limit,
            session_scope=session_scope,
            time_range=time_range,
        ))
        if selected_types:
            results = [
                item for item in results
                if item.metadata.get("artifact_type") in selected_types
                or item.metadata.get("kind") in selected_types
            ]
        results = self._dedupe_results(results, limit)
        raw_escalated = False
        if (
            (allow_raw_escalation if allow_raw_escalation is not None else request.allow_raw_escalation)
            and len(results) < max(2, limit // 2)
            and session_scope
        ):
            raw_escalated = True
            raw_results = self._fetch_raw_session_artifacts(
                session_scope,
                query,
                limit=self.config.search_v2.max_raw_artifacts,
            )
            results.extend(raw_results)
            results = self._dedupe_results(results, limit)
        confidence = min(1.0, sum(item.score for item in results[:3]) / max(1, min(3, len(results)))) if results else 0.0
        return {
            "query": query,
            "intent": request.intent,
            "retrieval_strategy": request.strategy,
            "confidence": confidence,
            "used_stores": selected_stores,
            "raw_escalated": raw_escalated,
            "count": len(results),
            "citations": [item.artifact_id for item in results[:limit]],
            "results": results[:limit],
        }

    def _fetch_raw_session_artifacts(self, session_key: str, query: str, limit: int = 4) -> list[RetrievedMemory]:
        query_lower = query.lower()
        matches: list[RetrievedMemory] = []
        for artifact in self.registry.list_artifacts("session_turn", limit=1000):
            if artifact.metadata.get("session_key") != session_key:
                continue
            haystack = f"{artifact.content}\n{artifact.summary}".lower()
            if query_lower not in haystack:
                continue
            idx = haystack.find(query_lower)
            snippet = artifact.content[max(0, idx - 100): idx + 220]
            matches.append(
                RetrievedMemory(
                    artifact_id=artifact.id,
                    store="raw",
                    score=0.55,
                    snippet=snippet,
                    reason="Escalated raw session evidence",
                    metadata={
                        **artifact.metadata,
                        "artifact_type": artifact.type,
                        "created_at": artifact.created_at,
                    },
                )
            )
            if len(matches) >= limit:
                break
        return matches

    def query(self, query: str, limit: int = 10) -> list[str]:
        results = self.search(query, top_k=limit)
        return [f"[{item.store}] {item.snippet}" for item in results]

    def doctor(self) -> dict[str, bool]:
        return {
            "file": True,
            "vector": self.vector_backend.healthcheck(),
            "graph": self.graph_backend.healthcheck(),
        }

    def get_artifact(self, artifact_id: str) -> MemoryArtifact | None:
        return self.registry.get_artifact(artifact_id)

    def get_entity(self, entity_ref: str) -> dict | None:
        row = self.registry.get_graph_node(entity_ref)
        if row is None:
            candidates = self.registry.find_graph_nodes(entity_ref, limit=1)
            row = candidates[0] if candidates else None
        if row is not None:
            edges = self.registry.get_graph_edges_for_node(row["id"])
            return {
                "id": row["id"],
                "label": row["label"],
                "metadata": json.loads(row["metadata_json"]),
                "edges": [
                    {
                        "source_id": edge["source_id"],
                        "target_id": edge["target_id"],
                        "relation": edge["relation"],
                        "weight": edge["weight"],
                        "metadata": json.loads(edge["metadata_json"]),
                    }
                    for edge in edges
                ],
            }
        for task_row in self.registry.search_task_nodes(entity_ref, limit=10):
            if entity_ref.lower() in task_row["title"].lower() or entity_ref.lower() in task_row["summary"].lower():
                edges: list[dict[str, object]] = []
                task_id = task_row["task_id"]
                for edge_row in self.registry.get_task_edges_for_node(task_id, task_row["node_id"], limit=16):
                    edges.append(
                        {
                            "source_id": edge_row["source_node_id"],
                            "target_id": edge_row["target_node_id"],
                            "relation": edge_row["relation"],
                            "metadata": json.loads(edge_row["metadata_json"]),
                        }
                    )
                return {
                    "id": task_row["node_id"],
                    "label": task_row["title"],
                    "metadata": {**json.loads(task_row["metadata_json"]), "task_id": task_id, "status": task_row["status"]},
                    "edges": edges,
                }
        return None

    def get_daily_note(self, day: str) -> dict | None:
        note_path = self.file_store.daily_dir / f"{day}.md"
        if not note_path.exists():
            return None
        return {"date": day, "path": str(note_path), "content": note_path.read_text(encoding="utf-8")}

    def get_task_state_summary(self, session_key: str) -> str:
        rows = self.registry.list_task_nodes(session_key, limit=4)
        if not rows:
            return ""
        return " | ".join(f"{row['node_type']}:{row['title']}[{row['status']}]" for row in rows)

    def get_recent_workflow_state(self, session_key: str) -> str:
        rows = self.registry.latest_workflow_snapshots(session_key, limit=2)
        if not rows:
            return ""
        return " | ".join(str(row["current_state"]) for row in rows)

    def record_workflow_snapshot(
        self,
        *,
        session_key: str,
        turn_id: str,
        step_index: int,
        goal: str,
        current_state: str,
        open_blockers: list[str],
        next_step: str,
        citations: list[str],
        tools_used: list[str],
    ) -> WorkflowStateArtifact | None:
        if not self.config.workflow_state.enabled:
            return None
        snapshot_id = hashlib.sha1(f"{session_key}:{turn_id}:{step_index}:{goal}".encode("utf-8")).hexdigest()[:16]
        created_at = datetime.now().isoformat()
        self.registry.insert_workflow_snapshot(
            snapshot_id=snapshot_id,
            session_key=session_key,
            turn_id=turn_id,
            step_index=step_index,
            goal=goal,
            current_state=current_state,
            open_blockers=open_blockers,
            next_step=next_step,
            citations=citations,
            tools_used=tools_used,
            created_at=created_at,
        )
        artifact = MemoryArtifact(
            id=f"workflow:{snapshot_id}",
            type="workflow_state",
            content=current_state,
            summary=f"{goal} -> {current_state}",
            metadata={
                "session_key": session_key,
                "turn_id": turn_id,
                "step_index": step_index,
                "open_blockers": open_blockers,
                "next_step": next_step,
                "citations": citations,
                "tools_used": tools_used,
                "artifact_type": "workflow_state",
                "timestamp": created_at,
            },
            source_ref="workflow",
            created_at=created_at,
        )
        self.registry.upsert_artifact(artifact)
        self.vector_backend.ingest_artifact(artifact)
        self._upsert_task_graph_for_snapshot(session_key, goal, artifact, open_blockers, next_step)
        return WorkflowStateArtifact(
            snapshot_id=snapshot_id,
            session_key=session_key,
            turn_id=turn_id,
            step_index=step_index,
            goal=goal,
            current_state=current_state,
            open_blockers=open_blockers,
            next_step=next_step,
            citations=citations,
            tools_used=tools_used,
        )

    def _upsert_task_graph_for_snapshot(
        self,
        session_key: str,
        goal: str,
        artifact: MemoryArtifact,
        open_blockers: list[str],
        next_step: str,
    ) -> None:
        if not self.config.task_graph.enabled:
            return
        task_id = f"task:{session_key}"
        goal_node = TaskNode(
            task_id=task_id,
            session_key=session_key,
            node_type="goal",
            title=goal[:120],
            status="active",
            summary=goal[:240],
            source_artifact_id=artifact.id,
        )
        step_node = TaskNode(
            task_id=task_id,
            session_key=session_key,
            node_type="step",
            title=artifact.id,
            status="done" if not open_blockers else "blocked",
            summary=artifact.summary[:240],
            source_artifact_id=artifact.id,
        )
        self.registry.upsert_task_node(goal_node, metadata={"node_id": task_id})
        self.registry.upsert_task_node(step_node, metadata={"node_id": artifact.id, "next_step": next_step})
        self.registry.upsert_task_edge(task_id, task_id, artifact.id, "supports_goal", {"artifact_id": artifact.id})
        if next_step:
            next_node = TaskNode(
                task_id=task_id,
                session_key=session_key,
                node_type="step",
                title=next_step[:120],
                status="pending",
                summary=next_step[:240],
                source_artifact_id=artifact.id,
            )
            next_id = f"next:{hashlib.sha1(next_step.encode('utf-8')).hexdigest()[:10]}"
            self.registry.upsert_task_node(next_node, metadata={"node_id": next_id})
            self.registry.upsert_task_edge(task_id, artifact.id, next_id, "depends_on", {"artifact_id": artifact.id})
        for blocker in open_blockers:
            blocker_node = TaskNode(
                task_id=task_id,
                session_key=session_key,
                node_type="blocker",
                title=blocker[:120],
                status="open",
                summary=blocker[:240],
                source_artifact_id=artifact.id,
            )
            blocker_id = f"blocker:{hashlib.sha1(blocker.encode('utf-8')).hexdigest()[:10]}"
            self.registry.upsert_task_node(blocker_node, metadata={"node_id": blocker_id})
            self.registry.upsert_task_edge(task_id, artifact.id, blocker_id, "blocks", {"artifact_id": artifact.id})

    def record_experience_event(
        self,
        *,
        category: str,
        session_key: str,
        trigger_text: str,
        recovery_text: str,
        metadata: dict[str, object] | None = None,
    ) -> MemoryArtifact | None:
        if not self.config.experience.enabled:
            return None
        normalized = f"{category}:{trigger_text.lower().strip()[:120]}"
        pattern_key = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
        event_id = hashlib.sha1(f"{pattern_key}:{datetime.now().isoformat()}".encode("utf-8")).hexdigest()[:16]
        self.registry.insert_experience_event(
            event_id=event_id,
            pattern_key=pattern_key,
            category=category,
            trigger_text=trigger_text,
            recovery_text=recovery_text,
            session_key=session_key,
            metadata=metadata or {},
            created_at=datetime.now().isoformat(),
        )
        pattern = self.registry.get_experience_pattern(pattern_key)
        if pattern is None:
            return None
        if self.config.experience.write_policy == "only_repeated_patterns" and pattern.evidence_count < self.config.experience.min_repeat_count:
            return None
        artifact = MemoryArtifact(
            id=f"experience:{pattern.pattern_key}",
            type="experience_pattern",
            content=f"Trigger: {pattern.trigger}\nRecovery: {pattern.recovery}",
            summary=f"{pattern.category}: {pattern.trigger}",
            metadata={
                "session_key": session_key,
                "artifact_type": "experience_pattern",
                "evidence_count": pattern.evidence_count,
                "category": pattern.category,
                "timestamp": pattern.last_seen_at,
            },
            source_ref="experience",
            created_at=pattern.last_seen_at,
        )
        self.registry.upsert_artifact(artifact)
        self.vector_backend.ingest_artifact(artifact)
        return artifact

    async def maybe_auto_summarize_session(self, session: "Session") -> MemoryArtifact | None:
        if not self.config.auto_summarize.enabled:
            return None
        current_tokens = int(session.metadata.get("estimated_context_tokens", 0))
        threshold = int(self.config.auto_summarize.max_context_tokens * self.config.auto_summarize.trigger_ratio)
        last_cutoff = int(session.metadata.get("summary_cutoff_idx", 0))
        if current_tokens < threshold:
            return None
        if len(session.messages) - last_cutoff < self.config.auto_summarize.min_new_messages:
            return None
        slice_messages = session.messages[last_cutoff:-max(1, min(6, len(session.messages)))] or session.messages[last_cutoff:]
        if not slice_messages:
            return None
        summary_text = await self._build_session_summary_text(session.key, slice_messages)
        covered_turns = [msg.get("turn_id", "") for msg in slice_messages if msg.get("turn_id")]
        source_refs = [msg.get("turn_id", "") for msg in slice_messages if msg.get("turn_id")]
        summary_id = hashlib.sha1(f"{session.key}:{covered_turns[:1]}:{covered_turns[-1:]}" .encode("utf-8")).hexdigest()[:16]
        self.registry.insert_session_rollup(
            summary_id=summary_id,
            session_key=session.key,
            covered_turns=covered_turns,
            summary=summary_text,
            open_items=[],
            source_refs=source_refs,
        )
        artifact = MemoryArtifact(
            id=f"session_summary:{summary_id}",
            type="session_summary",
            content=summary_text,
            summary=summary_text[:240],
            metadata={
                "session_key": session.key,
                "covered_turns": covered_turns,
                "artifact_type": "session_summary",
                "timestamp": datetime.now().isoformat(),
            },
            source_ref="session_rollup",
            created_at=datetime.now().isoformat(),
        )
        self.registry.upsert_artifact(artifact)
        self.vector_backend.ingest_artifact(artifact)
        if self.config.auto_summarize.archive_mode == "archive_continue":
            session.metadata["summary_cutoff_idx"] = max(last_cutoff, last_cutoff + len(slice_messages))
            trimmed_tokens = sum(len(str(msg.get("content", ""))) for msg in slice_messages) // 4
            session.metadata["estimated_context_tokens"] = max(
                0,
                int(session.metadata.get("estimated_context_tokens", 0)) - trimmed_tokens,
            )
        return artifact

    async def _build_session_summary_text(self, session_key: str, messages: list[dict]) -> str:
        auto_role = self.app_config.resolve_model_role("auto_summarize", self.model) if self.app_config else None
        prompt_text = self.prompts.load("system/auto-summarize.md").text if (self.prompts.root / "system" / "auto-summarize.md").exists() else (
            "Summarize the covered session slice with durable decisions, active threads, unresolved blockers, task outputs, and citations."
        )
        payload = "\n".join(
            f"[{msg.get('turn_id','?')}] {msg.get('role','?')}: {str(msg.get('content',''))[:500]}"
            for msg in messages
        )
        if self.provider and auto_role and auto_role.model:
            try:
                response = await self.provider.chat(
                    messages=[
                        {"role": "system", "content": prompt_text},
                        {"role": "user", "content": f"Session: {session_key}\n\n{payload}"},
                    ],
                    model=auto_role.model,
                    max_tokens=self.config.auto_summarize.summary_max_tokens,
                    temperature=0.1,
                )
                if response.content:
                    return response.content.strip()
            except Exception as exc:
                logger.warning("Auto-summary model failed for {}: {}", session_key, exc)
        return " | ".join(str(msg.get("content", "")).replace("\n", " ")[:180] for msg in messages[-6:])

    def build_runtime_context(self, session_key: str) -> str | None:
        parts: list[str] = []
        rollup = self.registry.latest_session_rollup(session_key)
        if rollup is not None:
            parts.append(f"Session Summary: {rollup['summary']}")
        task_state = self.get_task_state_summary(session_key)
        if task_state:
            parts.append(f"Task State: {task_state}")
        workflow_state = self.get_recent_workflow_state(session_key)
        if workflow_state:
            parts.append(f"Workflow State: {workflow_state}")
        return "\n".join(parts) if parts else None

    async def rebuild_vectors(self) -> int:
        artifacts = self.registry.list_artifacts(limit=10000)
        self.vector_backend.ingest_artifacts(artifacts)
        return len(artifacts)

    async def rebuild_graph(self) -> int:
        count = 0
        for artifact in self.registry.list_artifacts("session_turn", limit=10000):
            episode = EpisodeRecord(
                episode_id=artifact.id,
                session_key=artifact.metadata.get("session_key", ""),
                turn_id=artifact.metadata.get("turn_id", ""),
                channel=artifact.metadata.get("channel", ""),
                chat_id=artifact.metadata.get("chat_id", ""),
                user_text=artifact.content,
                assistant_text=artifact.summary,
                timestamp=artifact.created_at,
                metadata=artifact.metadata,
            )
            await self.graph_backend.ingest_episode_async(episode)
            count += 1
        return count

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def close(self) -> None:
        """Close backend resources."""
        return None


class NullMemoryOrchestrator:
    """Fallback used when memory initialization is unavailable in tests or degraded setups."""

    async def prepare_shadow_context(self, user_query: str, session_key: str, channel_context: dict[str, str]) -> ShadowBrief | None:
        return None

    def build_episode(self, session_key: str, turn_id: str, channel: str, chat_id: str, saved_entries: list[dict]) -> EpisodeRecord | None:
        return None

    async def enqueue_post_turn_ingest(self, episode: EpisodeRecord | None) -> None:
        return None

    async def consolidate_session(self, session: "Session") -> bool:
        return True

    async def backfill_sessions(self, sessions: list["Session"]) -> int:
        return 0

    def query(self, query: str, limit: int = 10) -> list[str]:
        return []

    def search(
        self,
        query: str,
        *,
        stores: list[str] | None = None,
        artifact_types: list[str] | None = None,
        top_k: int = 10,
        session_scope: str | None = None,
        time_range: dict[str, str] | None = None,
    ) -> list[RetrievedMemory]:
        return []

    def doctor(self) -> dict[str, bool]:
        return {"file": False, "vector": False, "graph": False}

    async def search_v2(
        self,
        query: str,
        *,
        strategy: str | None = None,
        stores: list[str] | None = None,
        artifact_types: list[str] | None = None,
        top_k: int | None = None,
        session_scope: str | None = None,
        time_range: dict[str, str] | None = None,
        allow_raw_escalation: bool | None = None,
    ) -> dict[str, object]:
        return {
            "query": query,
            "intent": "fresh_request",
            "retrieval_strategy": strategy or "balanced",
            "confidence": 0.0,
            "used_stores": stores or [],
            "raw_escalated": False,
            "count": 0,
            "citations": [],
            "results": [],
        }

    def get_artifact(self, artifact_id: str) -> MemoryArtifact | None:
        return None

    def get_entity(self, entity_ref: str) -> dict | None:
        return None

    def get_daily_note(self, day: str) -> dict | None:
        return None

    def get_task_state_summary(self, session_key: str) -> str:
        return ""

    def get_recent_workflow_state(self, session_key: str) -> str:
        return ""

    def record_workflow_snapshot(
        self,
        *,
        session_key: str,
        turn_id: str,
        step_index: int,
        goal: str,
        current_state: str,
        open_blockers: list[str],
        next_step: str,
        citations: list[str],
        tools_used: list[str],
    ):
        return None

    def record_experience_event(
        self,
        *,
        category: str,
        session_key: str,
        trigger_text: str,
        recovery_text: str,
        metadata: dict[str, object] | None = None,
    ):
        return None

    async def maybe_auto_summarize_session(self, session: "Session"):
        return None

    def build_runtime_context(self, session_key: str) -> str | None:
        return None

    async def rebuild_vectors(self) -> int:
        return 0

    async def rebuild_graph(self) -> int:
        return 0

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None
