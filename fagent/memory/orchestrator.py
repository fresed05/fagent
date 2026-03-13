"""Main orchestration layer for memory retrieval and ingestion."""

from __future__ import annotations

import json
import asyncio
import hashlib
import time
import re
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

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
    TurnIngestPlan,
    WorkflowStateArtifact,
)
from fagent.memory.vector import VectorMemoryBackend
from fagent.prompts import PromptLoader

if TYPE_CHECKING:
    from fagent.config.schema import Config, MemoryConfig
    from fagent.providers.base import LLMProvider
    from fagent.providers.factory import ProviderFactory
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
        provider_factory: "ProviderFactory | None" = None,
    ):
        from fagent.config.schema import MemoryConfig

        self.workspace = workspace
        self.provider = provider
        self.config = config or MemoryConfig()
        self.model = model
        self.provider_factory = provider_factory
        self.registry = MemoryRegistry(workspace)
        self.policy = MemoryPolicy()
        self.prompts = PromptLoader.from_package()
        self.app_config = app_config
        self.file_store = FileMemoryStore(workspace)
        embedding_role = app_config.resolve_model_role("embeddings") if app_config else None
        shadow_role = app_config.resolve_model_role("shadow", model) if app_config else None
        shadow_provider = provider
        auto_summarize_provider = provider
        if provider_factory and shadow_role and shadow_role.provider_kind not in ("", "inherit"):
            shadow_provider = provider_factory.build_from_profile(shadow_role)
        if provider_factory and app_config:
            auto_role = app_config.resolve_model_role("auto_summarize", model)
            if auto_role.provider_kind not in ("", "inherit"):
                auto_summarize_provider = provider_factory.build_from_profile(auto_role)
        self.shadow_provider = shadow_provider
        self.auto_summarize_provider = auto_summarize_provider
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
            provider=shadow_provider,
            model=(shadow_role.model if shadow_role else None),
            default_strategy=self.config.router.default_strategy,
            raw_evidence_escalation=self.config.router.raw_evidence_escalation,
            embedder=self.vector_backend,
        )
        self.shadow = ShadowContextBuilder(
            max_tokens=self.config.shadow_context.max_tokens,
        )
        self._tasks: set[asyncio.Task] = set()

    def _normalize_seed_artifact(
        self,
        artifact: MemoryArtifact | WorkflowStateArtifact,
    ) -> MemoryArtifact | None:
        if isinstance(artifact, MemoryArtifact):
            return artifact
        lookup_id = f"workflow:{artifact.snapshot_id}"
        existing = self.registry.get_artifact(lookup_id)
        if existing is not None:
            return existing
        normalized = MemoryArtifact(
            id=lookup_id,
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
        self.registry.upsert_artifact(normalized)
        return normalized

    async def _emit_stage(
        self,
        on_progress: Callable[..., Awaitable[None]] | None,
        *,
        stage: str,
        status: str,
        session_key: str,
        turn_id: str,
        detail: str = "",
        duration_ms: int | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        logger.bind(
            session_key=session_key,
            turn_id=turn_id,
            stage=stage,
            status=status,
            duration_ms=duration_ms,
            detail=detail[:240],
        ).info("turn_stage")
        if on_progress is None:
            return
        await on_progress(
            detail or stage,
            stage=stage,
            status=status,
            event="stage",
            session_key=session_key,
            turn_id=turn_id,
            duration_ms=duration_ms,
            extra=extra or {},
        )

    def _normalize_stage_error(self, stage: str, exc: Exception) -> tuple[str, dict[str, object]]:
        raw = str(exc).strip()
        lowered = raw.lower()
        if "workflowstateartifact" in lowered and "attribute 'id'" in lowered:
            return (
                "workflow snapshot normalization required",
                {
                    "reason": "workflow_snapshot_normalization_required",
                    "raw_error": raw[:240],
                    "stage": stage,
                },
            )
        return raw[:180], {"reason": "runtime_error", "raw_error": raw[:240], "stage": stage}

    @staticmethod
    def _normalize_repeat_text(value: str) -> str:
        text = re.sub(r"\s+", " ", (value or "").strip().lower())
        return re.sub(r"[^\w\s:/.-]+", "", text)

    def _is_repeat_request(self, user_text: str) -> bool:
        normalized = self._normalize_repeat_text(user_text)
        markers = (
            "повтори",
            "еще раз",
            "ещё раз",
            "еще",
            "ещё",
            "коротко",
            "в одну строку",
            "снова",
            "repeat",
            "again",
            "restate",
        )
        return any(marker in normalized for marker in markers)

    def _should_skip_graph_for_repeat(self, episode: EpisodeRecord) -> bool:
        if not episode.session_key or not self._is_repeat_request(episode.user_text):
            return False
        current = self._normalize_repeat_text(episode.assistant_text)
        if not current:
            return False
        recent = self.registry.list_session_artifacts(
            episode.session_key,
            artifact_type="session_turn",
            limit=8,
        )
        for artifact in recent:
            if artifact.id == episode.episode_id:
                continue
            previous = self._normalize_repeat_text(str(artifact.metadata.get("assistant_text") or ""))
            if not previous:
                continue
            similarity = SequenceMatcher(None, current, previous).ratio()
            if similarity >= 0.86 or current in previous or previous in current:
                return True
        return False

    def _ensure_session_artifact(self, episode: EpisodeRecord) -> MemoryArtifact:
        summary = self.policy.build_summary(episode)
        artifact = MemoryArtifact(
            id=episode.episode_id,
            type="session_turn",
            content=episode.content,
            summary=summary,
            metadata={
                "session_key": episode.session_key,
                "turn_id": episode.turn_id,
                "chat_id": episode.chat_id,
                "channel": episode.channel,
                "user_text": episode.user_text,
                "assistant_text": episode.assistant_text,
                "topic_tags": episode.metadata.get("topic_tags", []),
            },
            source_ref=episode.metadata.get("source_path", ""),
            created_at=episode.timestamp,
        )
        self.registry.upsert_artifact(artifact)
        return artifact

    @staticmethod
    def _extract_message_text(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "")
                if item_type == "text":
                    text = str(item.get("text") or "").strip()
                    if text:
                        parts.append(text)
                elif item_type == "image_url":
                    image_url = str((item.get("image_url") or {}).get("url") or "")
                    if image_url.startswith("data:image/"):
                        parts.append("[image]")
                    elif image_url:
                        parts.append(f"[image:{image_url[:80]}]")
            return "\n".join(part for part in parts if part)
        return str(content or "")

    @staticmethod
    def _summarize_tool_result(tool_name: str, content: str) -> dict[str, object]:
        text = str(content or "").strip()
        status = "error" if text.startswith("Error") else "ok"
        if len(text) > 420:
            head = text[:280].rstrip()
            tail = text[-100:].lstrip()
            snippet = f"{head}\n...\n{tail}"
        else:
            snippet = text
        return {
            "name": tool_name,
            "status": status,
            "summary": snippet[:420],
            "content_hash": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12] if text else "",
        }

    def _build_turn_ingest_plan(
        self,
        episode: EpisodeRecord,
        *,
        session: "Session",
        seed_artifacts: list[MemoryArtifact | WorkflowStateArtifact] | None = None,
    ) -> TurnIngestPlan:
        artifacts = [
            normalized
            for item in (seed_artifacts or [])
            if (normalized := self._normalize_seed_artifact(item)) is not None
        ]
        return TurnIngestPlan(
            episode=episode,
            artifacts=artifacts,
            graph_requested=True,
            vector_requested=True,
            summary_requested=bool(self.config.auto_summarize.enabled and session is not None),
            job_ids=[f"turn_ingest:{episode.episode_id}"],
        )

    def _ingest_file_memory(self, episode: EpisodeRecord, summary: str) -> list[MemoryArtifact]:
        del episode, summary
        return []

    async def _run_graph_stage(
        self,
        episode: EpisodeRecord,
        *,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        stage = "Building graph"
        started_at = time.perf_counter()
        if self._should_skip_graph_for_repeat(episode):
            await self._emit_stage(
                on_progress,
                stage=stage,
                status="skipped",
                session_key=episode.session_key,
                turn_id=episode.turn_id,
                detail="skipped: repeated_turn_already_in_graph",
            )
            return "skipped"
        await self._emit_stage(
            on_progress,
            stage=stage,
            status="started",
            session_key=episode.session_key,
            turn_id=episode.turn_id,
            detail="Launching graph mini-agent",
        )

        async def _graph_status(kind: str, detail: str, **extra: object) -> None:
            await self._emit_stage(
                on_progress,
                stage=stage,
                status="running",
                session_key=episode.session_key,
                turn_id=episode.turn_id,
                detail=detail,
                extra={"graph_phase": kind, **extra},
            )

        await self.graph_backend.ingest_episode_async(episode, status_callback=_graph_status)
        job = self.registry.get_graph_job(episode.episode_id)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        if job is None:
            await self._emit_stage(
                on_progress,
                stage=stage,
                status="failed",
                session_key=episode.session_key,
                turn_id=episode.turn_id,
                detail="Graph job missing after ingest",
                duration_ms=duration_ms,
            )
            return "failed"
        detail = job.status if not job.error else f"{job.status}: {job.error}"
        await self._emit_stage(
            on_progress,
            stage=stage,
            status=job.status,
            session_key=episode.session_key,
            turn_id=episode.turn_id,
            detail=detail,
            duration_ms=duration_ms,
            extra={"attempts": job.attempts, "error": job.error},
        )
        return job.status

    async def run_post_turn_pipeline(
        self,
        *,
        session: "Session",
        episode: EpisodeRecord | None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        seed_artifacts: list[MemoryArtifact | WorkflowStateArtifact] | None = None,
    ) -> dict[str, object]:
        if not self.config.enabled or episode is None:
            return {
                "file_memory": {"status": "skipped", "artifacts": 0},
                "graph": {"status": "skipped"},
                "vector": {"status": "skipped", "artifacts": 0},
                "summary": {"status": "skipped", "artifact_id": None},
            }

        if self.registry.get_job_status(episode.episode_id) == "done":
            return {
                "file_memory": {"status": "ok", "artifacts": 0},
                "graph": {"status": "done"},
                "vector": {"status": "ok", "artifacts": 0},
                "summary": {"status": "not_triggered", "artifact_id": None},
            }

        results: dict[str, object] = {
            "file_memory": {"status": "skipped", "artifacts": 0},
            "graph": {"status": "skipped"},
            "vector": {"status": "skipped", "artifacts": 0},
            "summary": {"status": "not_triggered", "artifact_id": None},
        }
        job_id = f"turn_ingest:{episode.episode_id}"
        stage_state = {
            "file_memory": "pending",
            "graph": "pending",
            "vector": "pending",
            "summary": "pending",
        }
        self.registry.upsert_post_turn_job(
            job_id=job_id,
            episode_id=episode.episode_id,
            session_key=episode.session_key,
            turn_id=episode.turn_id,
            stages=stage_state,
            status="running",
            attempt=0,
        )
        self.registry.set_job_status(episode.episode_id, "running")
        try:
            ingest_plan = self._build_turn_ingest_plan(episode, session=session, seed_artifacts=seed_artifacts)
            ingest_plan.artifacts.append(self._ensure_session_artifact(episode))
            results["file_memory"] = {"status": "skipped", "artifacts": 0, "reason": "explicit_only"}
            stage_state["file_memory"] = "skipped"
            await self._emit_stage(
                on_progress,
                stage="Saving file memory",
                status="skipped",
                session_key=episode.session_key,
                turn_id=episode.turn_id,
                detail="skipped: explicit_only",
            )
            self.registry.upsert_post_turn_job(
                job_id=job_id,
                episode_id=episode.episode_id,
                session_key=episode.session_key,
                turn_id=episode.turn_id,
                stages=stage_state,
                status="running",
                attempt=0,
            )

            graph_status = await self._run_graph_stage(episode, on_progress=on_progress)
            results["graph"] = {"status": graph_status}
            stage_state["graph"] = graph_status

            started_at = time.perf_counter()
            await self._emit_stage(
                on_progress,
                stage="Writing vectors",
                status="started",
                session_key=episode.session_key,
                turn_id=episode.turn_id,
                detail="Embedding post-turn artifact batch",
            )
            vector_artifacts = len(ingest_plan.artifacts)
            if self.vector_backend.embedding_client is None:
                results["vector"] = {"status": "skipped", "artifacts": 0, "reason": "vector_unavailable"}
                stage_state["vector"] = "skipped"
                await self._emit_stage(
                    on_progress,
                    stage="Writing vectors",
                    status="skipped",
                    session_key=episode.session_key,
                    turn_id=episode.turn_id,
                    detail="skipped: vector_unavailable",
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
            else:
                try:
                    self.vector_backend.ingest_artifacts(ingest_plan.artifacts)
                except Exception as exc:
                    error_detail, error_meta = self._normalize_stage_error("Writing vectors", exc)
                    results["vector"] = {"status": "retry", "artifacts": 0, "error": error_detail, "reason": error_meta.get("reason")}
                    stage_state["vector"] = "retry"
                    await self._emit_stage(
                        on_progress,
                        stage="Writing vectors",
                        status="retry",
                        session_key=episode.session_key,
                        turn_id=episode.turn_id,
                        detail=f"retry: {error_detail}",
                        duration_ms=int((time.perf_counter() - started_at) * 1000),
                        extra=error_meta,
                    )
                    raise
                results["vector"] = {"status": "ok", "artifacts": vector_artifacts}
                stage_state["vector"] = "ok"
                await self._emit_stage(
                    on_progress,
                    stage="Writing vectors",
                    status="ok",
                    session_key=episode.session_key,
                    turn_id=episode.turn_id,
                    detail=f"Wrote {vector_artifacts} vector payloads",
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                    extra={"artifacts": vector_artifacts},
                )
            self.registry.upsert_post_turn_job(
                job_id=job_id,
                episode_id=episode.episode_id,
                session_key=episode.session_key,
                turn_id=episode.turn_id,
                stages=stage_state,
                status="running",
                attempt=0,
            )

            try:
                results["summary"] = await self.run_auto_summary_stage(session, on_progress=on_progress, turn_id=episode.turn_id)
                artifact = results["summary"].get("artifact") if isinstance(results["summary"], dict) else None
                if isinstance(artifact, MemoryArtifact):
                    ingest_plan.artifacts.append(artifact)
                stage_state["summary"] = str(results["summary"].get("status", "done")) if isinstance(results["summary"], dict) else "done"
                if self.vector_backend.embedding_client is not None and isinstance(artifact, MemoryArtifact):
                    started_at = time.perf_counter()
                    self.vector_backend.ingest_artifacts([artifact])
                    results["vector"]["artifacts"] = int(results["vector"].get("artifacts", 0)) + 1 if isinstance(results["vector"], dict) else 1
                    results["vector"]["status"] = "ok"
                    await self._emit_stage(
                        on_progress,
                        stage="Writing vectors",
                        status="ok",
                        session_key=episode.session_key,
                        turn_id=episode.turn_id,
                        detail="Embedded summary artifact",
                        duration_ms=int((time.perf_counter() - started_at) * 1000),
                        extra={"artifacts": 1},
                    )
            except Exception as exc:
                error_detail, error_meta = self._normalize_stage_error("Summarizing session", exc)
                results["summary"] = {"status": "failed", "artifact_id": None, "error": error_detail, "reason": error_meta.get("reason")}
                stage_state["summary"] = "failed"
                await self._emit_stage(
                    on_progress,
                    stage="Summarizing session",
                    status="failed",
                    session_key=episode.session_key,
                    turn_id=episode.turn_id,
                    detail=error_detail,
                    extra=error_meta,
                )
                raise
            self.registry.upsert_post_turn_job(
                job_id=job_id,
                episode_id=episode.episode_id,
                session_key=episode.session_key,
                turn_id=episode.turn_id,
                stages=stage_state,
                status="done",
                attempt=0,
            )
            self.registry.set_job_status(episode.episode_id, "done")
            return results
        except Exception as exc:
            self.record_experience_event(
                category="environment_constraint",
                session_key=episode.session_key,
                trigger_text=f"ingest failed: {exc}",
                recovery_text="retry ingest later",
                metadata={"episode_id": episode.episode_id},
            )
            stage_state = {
                **stage_state,
                "error": str(exc)[:240],
            }
            self.registry.upsert_post_turn_job(
                job_id=job_id,
                episode_id=episode.episode_id,
                session_key=episode.session_key,
                turn_id=episode.turn_id,
                stages=stage_state,
                status="retry",
                attempt=1,
                last_error=str(exc)[:500],
            )
            self.registry.set_job_status(episode.episode_id, "retry", error=str(exc))
            logger.exception("Memory ingest failed for {}", episode.episode_id)
            if isinstance(results.get("vector"), dict) and results["vector"].get("status") == "skipped":
                pass
            else:
                await self._emit_stage(
                    on_progress,
                    stage="Turn memory",
                    status="failed",
                    session_key=episode.session_key,
                    turn_id=episode.turn_id,
                    detail=str(exc)[:240],
                )
            return results

    def _build_graph_backend(self, workspace: Path):
        graph_provider = self.provider
        graph_extract_model = None
        graph_normalize_model = None
        if self.app_config:
            graph_extract_role = self.app_config.resolve_model_role("graph_extract", self.model)
            graph_extract_model = graph_extract_role.model
            graph_normalize_model = self.app_config.resolve_model_role("graph_normalize", self.model).model
            if self.provider_factory and graph_extract_role.provider_kind not in ("", "inherit"):
                graph_provider = self.provider_factory.build_from_profile(graph_extract_role)
        if not self.config.graph.enabled:
            return LocalGraphBackend(
                workspace,
                self.registry,
                provider=graph_provider,
                extract_model=graph_extract_model,
                normalize_model=graph_normalize_model,
                prompt_loader=self.prompts,
                semantic_embedder=self.vector_backend,
            )
        if self.config.graph.backend == "graphiti-neo4j" and self.config.graph.uri:
            return Neo4jGraphBackend(
                workspace,
                self.registry,
                uri=self.config.graph.uri,
                username=self.config.graph.username,
                password=self.config.graph.password,
                provider=graph_provider,
                extract_model=graph_extract_model,
                normalize_model=graph_normalize_model,
                prompt_loader=self.prompts,
                semantic_embedder=self.vector_backend,
            )
        return LocalGraphBackend(
            workspace,
            self.registry,
            provider=graph_provider,
            extract_model=graph_extract_model,
            normalize_model=graph_normalize_model,
            prompt_loader=self.prompts,
            semantic_embedder=self.vector_backend,
        )

    async def prepare_shadow_context(
        self,
        user_query: str,
        session_key: str,
        channel_context: dict[str, str],
        *,
        presearch_bundle: dict[str, object] | None = None,
    ) -> ShadowBrief | None:
        if not self.config.enabled or not self.config.shadow_context.enabled:
            return None
        bundle = presearch_bundle or await self.search_v2(
            user_query,
            session_scope=session_key,
        )
        brief = await self.shadow.build(
            user_query,
            session_key,
            channel_context,
            evidence_bundle=bundle,
            working_set=self._session_working_set(session_key),
        )
        if brief is not None:
            brief.retrieval_strategy = (
                f"router:{bundle.get('intent', 'fresh_request')}:{bundle.get('retrieval_strategy', 'balanced')}"
            )
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
        tool_summaries: list[dict[str, object]] = []
        evidence_blocks: list[str] = []
        timestamp = None
        source_path = str(self.workspace / "sessions")
        for entry in saved_entries:
            role = entry.get("role")
            content = entry.get("content")
            if role == "user":
                extracted = self._extract_message_text(content)
                if extracted:
                    user_text = extracted
                    if isinstance(content, list):
                        evidence_blocks.append(f"user_media: {extracted[:220]}")
                timestamp = entry.get("timestamp", timestamp)
            elif role == "assistant" and isinstance(content, str):
                assistant_text = content
                timestamp = entry.get("timestamp", timestamp)
            elif role == "assistant" and entry.get("tool_calls"):
                tools.extend(call["function"]["name"] for call in entry["tool_calls"])
            elif role == "tool":
                tool_name = str(entry.get("name", "tool"))
                tools.append(tool_name)
                tool_summary = self._summarize_tool_result(tool_name, self._extract_message_text(content))
                tool_summaries.append(tool_summary)
                if tool_summary.get("summary"):
                    evidence_blocks.append(f"{tool_name}: {str(tool_summary['summary'])[:220]}")
        if not user_text and not assistant_text:
            return None
        episode_id = hashlib.sha1(f"{session_key}:{turn_id}".encode("utf-8")).hexdigest()[:16]
        topic_tags = self.policy.extract_topic_tags(
            "\n".join(part for part in [user_text, assistant_text, *[str(block) for block in evidence_blocks]] if part)
        )
        return EpisodeRecord(
            episode_id=episode_id,
            session_key=session_key,
            turn_id=turn_id,
            channel=channel,
            chat_id=chat_id,
            user_text=user_text,
            assistant_text=assistant_text,
            tool_trace=tools,
            tool_summaries=tool_summaries,
            evidence_blocks=evidence_blocks,
            timestamp=timestamp or "",
            metadata={"topic_tags": topic_tags, "source_path": source_path},
        )

    async def enqueue_post_turn_ingest(
        self,
        *,
        session: "Session",
        episode: EpisodeRecord | None,
        seed_artifacts: list[MemoryArtifact | WorkflowStateArtifact] | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        if not self.config.enabled or episode is None:
            return
        if self.registry.get_job_status(episode.episode_id) == "done":
            return
        if not self.config.ingest.async_enabled:
            await self.ingest_episode(session=session, episode=episode, seed_artifacts=seed_artifacts, on_progress=on_progress)
            return

        async def _runner() -> None:
            try:
                await self.ingest_episode(session=session, episode=episode, seed_artifacts=seed_artifacts, on_progress=on_progress)
            finally:
                task = asyncio.current_task()
                if task is not None:
                    self._tasks.discard(task)

        task = asyncio.create_task(_runner())
        self._tasks.add(task)

    async def ingest_episode(
        self,
        episode: EpisodeRecord,
        *,
        session: "Session | None" = None,
        seed_artifacts: list[MemoryArtifact | WorkflowStateArtifact] | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        class _SyntheticSession:
            def __init__(self, key: str) -> None:
                self.key = key
                self.messages: list[dict[str, object]] = []
                self.metadata: dict[str, object] = {}

        await self.run_post_turn_pipeline(
            session=session or _SyntheticSession(episode.session_key),
            episode=episode,
            on_progress=on_progress,
            seed_artifacts=seed_artifacts,
        )

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
                await self.enqueue_post_turn_ingest(session=session, episode=episode)
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
                await self.ingest_episode(episode, session=session)
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
                vector_filters: dict[str, object] = {}
                if session_scope:
                    vector_filters["session_key"] = session_scope
                if artifact_types:
                    vector_filters["artifact_type"] = artifact_types
                results.extend(self.vector_backend.retrieve(query, limit=top_k, filters=vector_filters or None))
        except Exception as exc:
            logger.warning("Vector retrieval failed for query '{}': {}", query, exc)
        try:
            if "graph" in selected:
                results.extend(self.graph_backend.retrieve(query, limit=top_k))
        except Exception as exc:
            logger.warning("Graph retrieval failed for query '{}': {}", query, exc)
        if session_scope:
            results = [
                item for item in results
                if item.metadata.get("session_key") in ("", None, session_scope)
            ]
        if artifact_types:
            results = [item for item in results if self._artifact_matches_filters(item, artifact_types)]
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

    @staticmethod
    def _artifact_matches_filters(item: RetrievedMemory, artifact_types: list[str]) -> bool:
        if not artifact_types:
            return True
        item_type = str(item.metadata.get("artifact_type") or "")
        item_kind = str(item.metadata.get("kind") or "")
        if item_type in artifact_types or item_kind in artifact_types:
            return True
        if item.store == "file":
            path = str(item.metadata.get("path") or "")
            if "file_note" in artifact_types and path.endswith(".md"):
                return True
            if "fact" in artifact_types and path.endswith("MEMORY.md"):
                return True
        return False

    def _session_working_set(self, session_key: str) -> dict[str, object]:
        active_task_state = self.get_task_state_summary(session_key)
        recent_workflow_state = self.get_recent_workflow_state(session_key)
        current_decisions: list[str] = []
        open_blockers: list[str] = []
        active_entities: list[str] = []
        for row in self.registry.list_task_nodes(session_key, limit=12):
            node_type = str(row["node_type"])
            title = str(row["title"])
            status = str(row["status"])
            summary = str(row["summary"])
            if node_type == "decision":
                current_decisions.append(f"{title} | {summary}"[:220])
            if node_type == "blocker" or status in {"blocked", "open"}:
                open_blockers.append(f"{title} | {summary}"[:220])
            if node_type in {"goal", "entity"}:
                active_entities.append(title[:120])
        return {
            "active_task_state": active_task_state,
            "recent_workflow_state": recent_workflow_state,
            "current_decisions": current_decisions[:3],
            "open_blockers": open_blockers[:3],
            "active_entities": active_entities[:6],
        }

    @staticmethod
    def _parse_timestamp(value: str | None) -> float:
        if not value:
            return 0.0
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    def _candidate_score(
        self,
        item: RetrievedMemory,
        *,
        route: MemorySearchRequestV2,
        store_rank: dict[str, int],
        seen_recent: set[str],
    ) -> float:
        store_pref = max(0.0, 1.0 - 0.08 * store_rank.get(item.store, 5))
        semantic = item.score
        ts = str(item.metadata.get("timestamp") or item.metadata.get("created_at") or "")
        recency = 0.0
        if ts:
            age_seconds = max(0.0, time.time() - self._parse_timestamp(ts))
            recency = max(0.0, 1.0 - min(1.0, age_seconds / (14 * 24 * 3600)))
        temporal_bonus = 0.12 if route.intent == "temporal_recall" and ts else 0.0
        novelty_bonus = route.novelty_target if item.artifact_id not in seen_recent else -0.08
        contradiction_bonus = 0.14 if (
            item.metadata.get("superseded")
            or "contradict" in item.reason.lower()
            or item.metadata.get("node_type") == "blocker"
        ) else 0.0
        return 0.58 * semantic + 0.16 * store_pref + 0.12 * recency + temporal_bonus + novelty_bonus + contradiction_bonus

    def _rrf_merge(self, ranked_lists: list[list[RetrievedMemory]], k: int = 60) -> list[RetrievedMemory]:
        merged: dict[str, RetrievedMemory] = {}
        scores: dict[str, float] = {}
        for ranked in ranked_lists:
            for index, item in enumerate(ranked, start=1):
                scores[item.artifact_id] = scores.get(item.artifact_id, 0.0) + 1.0 / (k + index)
                existing = merged.get(item.artifact_id)
                if existing is None or item.score > existing.score:
                    merged[item.artifact_id] = item
        fused = []
        for artifact_id, item in merged.items():
            fused.append(
                RetrievedMemory(
                    artifact_id=item.artifact_id,
                    store=item.store,
                    score=min(1.0, item.score + scores.get(artifact_id, 0.0)),
                    snippet=item.snippet,
                    reason=item.reason,
                    metadata=item.metadata,
                )
            )
        fused.sort(key=lambda item: item.score, reverse=True)
        return fused

    def _lexical_variant(self, query: str) -> str:
        compact = re.sub(r"[^\w\s:/.-]+", " ", query.lower())
        compact = re.sub(r"\s+", " ", compact).strip()
        squashed = compact.replace(" ", "")
        return squashed if 6 <= len(squashed) <= 32 else compact

    def _semantic_variant(self, query: str, route: MemorySearchRequestV2) -> str:
        if route.intent == "relationship_recall":
            return f"relationship graph {query}".strip()
        if route.intent == "workflow_recall":
            return f"workflow blocker steps {query}".strip()
        if route.intent == "continuity":
            return f"current state continue {query}".strip()
        return f"{route.intent.replace('_', ' ')} {query}".strip()

    def _expand_query_variants(
        self,
        query: str,
        route: MemorySearchRequestV2,
        *,
        first_pass_count: int = 0,
    ) -> list[str]:
        variants = [variant for variant in route.query_variants if variant and variant != query]
        hard_query = (
            len(query.split()) < 4
            or route.route_confidence < 0.62
            or first_pass_count < 3
        )
        if not hard_query:
            return variants[:2]
        lexical = self._lexical_variant(query)
        semantic = self._semantic_variant(query, route)
        for candidate in (lexical, semantic):
            if candidate and candidate != query and candidate not in variants:
                variants.append(candidate)
            if len(variants) >= 2:
                break
        return variants[:2]

    def _structured_results_for_query(
        self,
        query: str,
        request: MemorySearchRequestV2,
        *,
        session_scope: str | None,
    ) -> list[RetrievedMemory]:
        limit = max(3, request.candidate_budget.get("final", self.config.search_v2.default_top_k))
        results: list[RetrievedMemory] = []
        if request.intent in {"continuity", "broad_synthesis"} and session_scope:
            results.extend(self._latest_session_summary_result(session_scope))
        if request.intent in {"continuity", "workflow_recall", "relationship_recall"} and session_scope:
            results.extend(self._task_graph_results(session_scope, query, request.candidate_budget.get("task_graph", limit)))
        if request.intent == "workflow_recall" and session_scope:
            results.extend(self._workflow_snapshot_results(session_scope, request.candidate_budget.get("workflow", limit)))
            results.extend(self._experience_results(session_scope, query, request.candidate_budget.get("experience", 4)))
        elif request.intent in {"factual_recall", "preference_recall"}:
            results.extend(self._experience_results(session_scope, query, request.candidate_budget.get("experience", 4)))
        return results

    def _search_store(
        self,
        query: str,
        store: str,
        *,
        limit: int,
        session_scope: str | None,
        artifact_types: list[str],
        time_range: dict[str, str] | None,
    ) -> list[RetrievedMemory]:
        if store in {"summary", "task_graph", "workflow", "experience"}:
            return []
        return self.search(
            query,
            stores=[store],
            artifact_types=artifact_types,
            top_k=limit,
            session_scope=session_scope,
            time_range=time_range,
        )

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
        selected_types = artifact_types or request.artifact_types or []
        limit = top_k or request.candidate_budget.get("final") or self.config.search_v2.default_top_k
        store_rank = {store: index for index, store in enumerate(selected_stores)}
        if hasattr(self.vector_backend, "reset_query_embedding_stats"):
            self.vector_backend.reset_query_embedding_stats()
        variant_queries = [query]
        initial_structured = self._structured_results_for_query(query, request, session_scope=session_scope)
        initial_store_lists: list[list[RetrievedMemory]] = []
        store_contributions: dict[str, int] = {}
        per_store_hits: dict[str, int] = defaultdict(int)
        store_queries = 0
        if initial_structured:
            initial_store_lists.append(initial_structured)
            for item in initial_structured:
                store_contributions[item.store] = store_contributions.get(item.store, 0) + 1
                per_store_hits[item.store] += 1
        for store in selected_stores:
            store_queries += 1
            pool_limit = request.candidate_budget.get(store, max(limit, 4))
            hits = self._search_store(
                query,
                store,
                limit=pool_limit,
                session_scope=session_scope,
                artifact_types=selected_types,
                time_range=time_range,
            )
            if hits:
                initial_store_lists.append(hits)
                store_contributions[store] = store_contributions.get(store, 0) + len(hits)
                per_store_hits[store] += len(hits)
        first_pass = self._rrf_merge(initial_store_lists) if initial_store_lists else []
        for variant in self._expand_query_variants(query, request, first_pass_count=len(first_pass)):
            if variant not in variant_queries:
                variant_queries.append(variant)

        ranked_lists: list[list[RetrievedMemory]] = list(initial_store_lists)
        for variant in variant_queries[1:]:
            structured = self._structured_results_for_query(variant, request, session_scope=session_scope)
            if structured:
                ranked_lists.append(structured)
                for item in structured:
                    store_contributions[item.store] = store_contributions.get(item.store, 0) + 1
                    per_store_hits[item.store] += 1
            for store in selected_stores:
                store_queries += 1
                pool_limit = request.candidate_budget.get(store, max(limit, 4))
                hits = self._search_store(
                    variant,
                    store,
                    limit=pool_limit,
                    session_scope=session_scope,
                    artifact_types=selected_types,
                    time_range=time_range,
                )
                if not hits:
                    continue
                ranked_lists.append(hits)
                store_contributions[store] = store_contributions.get(store, 0) + len(hits)
                per_store_hits[store] += len(hits)

        results = self._rrf_merge(ranked_lists) if ranked_lists else []
        if selected_types:
            results = [item for item in results if self._artifact_matches_filters(item, selected_types)]
        shadow_state = self.shadow.session_history.get(session_scope or "") if session_scope else None
        recent_citations = set(shadow_state.last_citations if shadow_state else [])
        rescored = [
            RetrievedMemory(
                artifact_id=item.artifact_id,
                store=item.store,
                score=self._candidate_score(
                    item,
                    route=request,
                    store_rank=store_rank,
                    seen_recent=recent_citations,
                ),
                snippet=item.snippet,
                reason=item.reason,
                metadata=item.metadata,
            )
            for item in results
        ]
        results = self._dedupe_results(rescored, max(limit, request.candidate_budget.get("final", limit)))
        raw_escalated = False
        raw_escalation_requested = allow_raw_escalation if allow_raw_escalation is not None else request.allow_raw_escalation
        if (
            raw_escalation_requested
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
            rescored = [
                RetrievedMemory(
                    artifact_id=item.artifact_id,
                    store=item.store,
                    score=self._candidate_score(
                        item,
                        route=request,
                        store_rank=store_rank,
                        seen_recent=recent_citations,
                    ),
                    snippet=item.snippet,
                    reason=item.reason,
                    metadata=item.metadata,
                )
                for item in results
            ]
            results = self._dedupe_results(rescored, limit)
            per_store_hits["raw"] += len(raw_results)
        confidence = min(1.0, sum(item.score for item in results[:3]) / max(1, min(3, len(results)))) if results else 0.0
        diagnostics = self._build_search_diagnostics(
            query=query,
            selected_stores=selected_stores,
            selected_types=selected_types,
            session_scope=session_scope,
            time_range=time_range,
            allow_raw_requested=raw_escalation_requested,
            raw_escalated=raw_escalated,
            per_store_hits=per_store_hits,
            results=results,
        )
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
            "semantic_score": request.semantic_score,
            "rule_score": request.rule_score,
            "route_confidence": request.route_confidence,
            "route_reason": request.route_reason,
            "query_variants": variant_queries[1:],
            "candidate_budget": request.candidate_budget,
            "novelty_target": request.novelty_target,
            "store_contributions": store_contributions,
            "variant_count": max(0, len(variant_queries) - 1),
            "store_queries_per_search": store_queries,
            "embedding_requests_per_search": self.vector_backend.query_embedding_stats().get("requests", 0),
            "embedding_cache_hits_per_search": self.vector_backend.query_embedding_stats().get("cache_hits", 0),
            "raw_escalations": 1 if raw_escalated else 0,
            "graph_search_candidates_scanned": getattr(self.graph_backend, "last_search_candidate_count", 0),
            **diagnostics,
        }

    def _fetch_raw_session_artifacts(self, session_key: str, query: str, limit: int = 4) -> list[RetrievedMemory]:
        query_lower = query.lower()
        matches: list[RetrievedMemory] = []
        for artifact in self.registry.search_artifacts(
            query,
            session_key=session_key,
            artifact_type="session_turn",
            limit=max(limit * 4, limit),
        ):
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

    def _store_health_snapshot(self) -> dict[str, bool]:
        return {
            "file": True,
            "vector": self.vector_backend.healthcheck(),
            "graph": self.graph_backend.healthcheck(),
        }

    def _build_search_diagnostics(
        self,
        *,
        query: str,
        selected_stores: list[str],
        selected_types: list[str],
        session_scope: str | None,
        time_range: dict[str, str] | None,
        allow_raw_requested: bool,
        raw_escalated: bool,
        per_store_hits: dict[str, int],
        results: list[RetrievedMemory],
    ) -> dict[str, object]:
        store_health = self._store_health_snapshot()
        store_attempts = {
            store: {
                "attempted": True,
                "healthy": store_health.get(store, False) if store in {"vector", "graph"} else True,
                "hits": per_store_hits.get(store, 0),
            }
            for store in selected_stores
        }
        empty_reason_codes: list[str] = []
        if allow_raw_requested and not session_scope:
            raw_escalation_reason = "raw_escalation_skipped_no_session_scope"
        elif raw_escalated:
            raw_escalation_reason = "raw_escalated"
        elif allow_raw_requested and session_scope:
            raw_escalation_reason = "raw_escalation_not_triggered"
        else:
            raw_escalation_reason = "not_requested"

        if not results:
            empty_reason_codes.append("no_matching_data")
            if "file" in selected_stores and not any(path.exists() for path in self.file_store._candidate_files()):
                empty_reason_codes.append("file_source_disabled")
            unavailable = [store for store in selected_stores if not store_attempts.get(store, {}).get("healthy", True)]
            if unavailable:
                empty_reason_codes.append("store_unavailable")
            if any(store_health.get(store, True) for store in selected_stores):
                empty_reason_codes.append("query_data_mismatch")
            if "graph" in selected_stores and per_store_hits.get("graph", 0) == 0:
                empty_reason_codes.append("graph_no_entity_match")
            if "vector" in selected_stores and session_scope and store_health.get("vector", False):
                unscoped_hits = self.search(
                    query,
                    stores=["vector"],
                    artifact_types=selected_types,
                    top_k=max(4, self.config.search_v2.default_top_k),
                    session_scope=None,
                    time_range=time_range,
                )
                if unscoped_hits:
                    empty_reason_codes.append("vector_filtered_out_by_scope")
            elif "vector" in selected_stores and not store_health.get("vector", False):
                empty_reason_codes.append("embedding_failed")
        elif allow_raw_requested and not raw_escalated and not session_scope and len(results) < max(2, len(selected_stores)):
            empty_reason_codes.append("raw_escalation_skipped_no_session_scope")

        deduped_codes: list[str] = []
        for code in empty_reason_codes:
            if code not in deduped_codes:
                deduped_codes.append(code)
        return {
            "store_health": store_health,
            "store_attempts": store_attempts,
            "empty_reason_codes": deduped_codes,
            "raw_escalation_reason": raw_escalation_reason,
            "session_scope_applied": bool(session_scope),
            "filters_applied": {
                "artifact_types": selected_types,
                "time_range": bool(time_range),
            },
        }

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
        match_source = "direct_id"
        match_confidence = 1.0
        if row is None:
            candidates = self.graph_backend.search_candidates(entity_ref, limit=3)
            if candidates:
                top = candidates[0]
                candidate_score = float(top.get("search_score", 0.0) or 0.0)
                if candidate_score >= 0.2:
                    row = self.registry.get_graph_node(str(top["id"]))
                    match_source = "ranked_graph_search"
                    match_confidence = candidate_score
        if row is not None:
            edges = self.registry.get_graph_edges_for_node(row["id"], limit=256)
            neighbor_ids = {
                str(edge["target_id"]) if str(edge["source_id"]) == str(row["id"]) else str(edge["source_id"])
                for edge in edges
            }
            neighbors = []
            for neighbor_id in neighbor_ids:
                neighbor_row = self.registry.get_graph_node(neighbor_id)
                if neighbor_row is None:
                    continue
                neighbors.append(
                    {
                        "id": neighbor_row["id"],
                        "label": neighbor_row["label"],
                        "metadata": json.loads(neighbor_row["metadata_json"]) if neighbor_row["metadata_json"] else {},
                    }
                )
            return {
                "id": row["id"],
                "label": row["label"],
                "resolution": "graph_entity",
                "match_source": match_source,
                "match_confidence": match_confidence,
                "metadata": {
                    **json.loads(row["metadata_json"]),
                    "resolution": "graph_entity",
                    "match_source": match_source,
                    "match_confidence": match_confidence,
                },
                "neighbors": neighbors,
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
                    "resolution": "task_graph",
                    "match_source": "task_graph_search",
                    "match_confidence": 0.74,
                    "metadata": {
                        **json.loads(task_row["metadata_json"]),
                        "task_id": task_id,
                        "status": task_row["status"],
                        "resolution": "task_graph",
                        "match_source": "task_graph_search",
                        "match_confidence": 0.74,
                    },
                    "edges": edges,
                }
        artifact_matches = self.registry.search_artifacts(entity_ref, limit=3)
        if artifact_matches:
            primary = artifact_matches[0]
            primary_text = f"{primary.summary}\n{primary.content}".lower()
            query_tokens = [token for token in re.split(r"\W+", entity_ref.lower()) if len(token) >= 3]
            if query_tokens and not any(token in primary_text for token in query_tokens):
                return None
            fallback_confidence = 0.45
            return {
                "id": f"artifact:{primary.id}",
                "label": entity_ref,
                "resolution": "artifact_fallback",
                "match_source": "artifact_search",
                "match_confidence": fallback_confidence,
                "metadata": {
                    "kind": "artifact_fallback",
                    "degraded": True,
                    "confidence": fallback_confidence,
                    "resolution": "artifact_fallback",
                    "match_source": "artifact_search",
                    "match_confidence": fallback_confidence,
                    "artifact_id": primary.id,
                    "artifact_type": primary.type,
                    "source_ref": primary.source_ref,
                    **primary.metadata,
                },
                "neighbors": [
                    {
                        "id": item.id,
                        "label": item.summary[:180] or item.id,
                        "metadata": {
                            **item.metadata,
                            "artifact_type": item.type,
                            "source_ref": item.source_ref,
                        },
                    }
                    for item in artifact_matches[1:]
                ],
                "edges": [],
            }
        return None

    def semantic_search_nodes(self, query: str, top_k: int = 5, include_edges: bool = True) -> list[dict]:
        """Semantic search over graph nodes using embeddings."""
        if not self.vector_backend:
            return []

        try:
            query_vector = self.vector_backend.embed(query)
            node_embeddings = self.registry.get_all_node_embeddings()

            if not node_embeddings:
                return []

            # Compute cosine similarity
            scores = []
            for node_id, node_vector in node_embeddings:
                similarity = self._cosine_similarity(query_vector, node_vector)
                scores.append((node_id, similarity))

            # Sort by similarity and take top_k
            scores.sort(key=lambda x: x[1], reverse=True)
            top_nodes = scores[:top_k]

            results = []
            for node_id, score in top_nodes:
                node_row = self.registry.get_graph_node(node_id)
                if not node_row:
                    continue

                result = {
                    "id": node_row["id"],
                    "label": node_row["label"],
                    "score": score,
                    "metadata": json.loads(node_row["metadata_json"]) if node_row["metadata_json"] else {},
                }

                if include_edges:
                    edges = self.registry.get_graph_edges_for_node(node_id, limit=16)
                    result["edges"] = [
                        {
                            "source_id": edge["source_id"],
                            "target_id": edge["target_id"],
                            "relation": edge["relation"],
                            "weight": edge["weight"],
                        }
                        for edge in edges
                    ]

                results.append(result)

            return results
        except Exception as exc:
            logger.warning("Semantic search failed: {}", exc)
            return []

    @staticmethod
    def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        return dot_product / (magnitude1 * magnitude2)

    def export_graph_subgraph(
        self,
        *,
        query: str | None = None,
        session_key: str | None = None,
        mode: str = "global-clustered",
        focus_node: str | None = None,
        node_limit: int = 200,
        edge_limit: int = 400,
    ) -> dict[str, object]:
        node_ids = self.registry.recent_graph_node_ids_for_session(session_key, limit=node_limit) if session_key else None
        raw_nodes = self.registry.list_graph_nodes(query=query, node_ids=node_ids, limit=node_limit)
        nodes = []
        for row in raw_nodes:
            metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            kind = str(metadata.get("kind") or "")
            confidence = float(metadata.get("confidence", 1.0) or 1.0)
            aliases = metadata.get("aliases") or []
            if not query and kind == "concept" and confidence <= 0.5 and len(aliases) <= 1:
                continue
            nodes.append(row)
        resolved_ids = [str(row["id"]) for row in nodes]
        edges = self.registry.list_graph_edges(node_ids=resolved_ids if resolved_ids else node_ids, limit=edge_limit)
        layouts = self.registry.load_graph_layouts(resolved_ids)
        layout_map = {
            str(row["node_id"]): {
                "x": float(row["x"]),
                "y": float(row["y"]),
                "pinned": bool(row["pinned"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in layouts
        }
        node_payloads = [
            {
                "id": str(row["id"]),
                "label": str(row["label"]),
                "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                "degree": int(row["degree"]) if "degree" in row.keys() else 0,
                "layout": layout_map.get(str(row["id"])),
            }
            for row in nodes
        ]
        edge_payloads = [
            {
                "source_id": str(row["source_id"]),
                "target_id": str(row["target_id"]),
                "relation": str(row["relation"]),
                "weight": float(row["weight"]),
                "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            }
            for row in edges
        ]
        requested_mode = mode or "global-clustered"
        raw_mode = requested_mode == "global-raw"
        focus_mode = requested_mode == "focus-expand"
        needs_cluster_fallback = raw_mode and (
            len(node_payloads) > 90 or len(edge_payloads) > 180
        )
        effective_mode = "global-clustered" if needs_cluster_fallback else requested_mode
        if focus_mode:
            focused_payload = self._focus_graph_snapshot(
                node_payloads,
                edge_payloads,
                focus_node=focus_node,
                query=query,
            )
            node_payloads = focused_payload["nodes"]
            edge_payloads = focused_payload["edges"]
        if effective_mode == "global-clustered":
            clustered = self._cluster_graph_snapshot(node_payloads, edge_payloads)
            node_payloads = clustered["nodes"]
            edge_payloads = clustered["edges"]
            clusters = clustered["clusters"]
            hidden_node_count = clustered["hidden_node_count"]
            hidden_edge_count = clustered["hidden_edge_count"]
        else:
            clusters = []
            hidden_node_count = 0
            hidden_edge_count = 0
        message = (
            "Loaded latest graph snapshot."
            if resolved_ids and not query and not session_key
            else ("" if resolved_ids else "No graph items matched the current scope.")
        )
        if needs_cluster_fallback:
            message = (
                f"Raw graph exceeded safe limits ({len(node_payloads)} nodes / {len(edge_payloads)} edges). "
                "Switched to clustered mode."
            )
        elif effective_mode == "focus-expand" and focus_node:
            message = f"Focused on {focus_node}."
        return {
            "nodes": node_payloads,
            "edges": edge_payloads,
            "clusters": clusters,
            "mode": effective_mode,
            "requested_mode": requested_mode,
            "hidden_node_count": hidden_node_count,
            "hidden_edge_count": hidden_edge_count,
            "message": message,
        }

    def export_graph_overview(
        self,
        *,
        query: str | None = None,
        session_key: str | None = None,
        mode: str = "global-clustered",
        node_limit: int = 200,
        edge_limit: int = 400,
    ) -> dict[str, object]:
        payload = self.export_graph_subgraph(
            query=query,
            session_key=session_key,
            mode=mode,
            node_limit=node_limit,
            edge_limit=edge_limit,
        )
        for node in payload.get("nodes", []):
            metadata = dict(node.get("metadata") or {})
            metadata.setdefault("view_role", "overview")
            metadata.setdefault("priority_score", self._graph_priority_score(node))

            tier = node.get("tier", 3)
            metadata["visual"] = {
                "size": {1: 40, 2: 25, 3: 15}.get(tier, 15),
                "color": {1: "#FF6B6B", 2: "#4ECDC4", 3: "#95E1D3"}.get(tier, "#95E1D3"),
                "strokeWidth": {1: 3, 2: 2, 3: 1}.get(tier, 1),
                "fontSize": {1: 16, 2: 12, 3: 10}.get(tier, 10),
                "opacity": {1: 1.0, 2: 0.9, 3: 0.8}.get(tier, 0.8)
            }

            node["metadata"] = metadata
        search_results = [
            {
                "id": str(node["id"]),
                "label": str(node["label"]),
                "kind": str((node.get("metadata") or {}).get("kind") or "node"),
                "is_cluster": bool((node.get("metadata") or {}).get("is_cluster")),
                "priority_score": int((node.get("metadata") or {}).get("priority_score") or self._graph_priority_score(node)),
            }
            for node in payload.get("nodes", [])
            if self._include_graph_search_result(node)
        ]
        search_results.sort(
            key=lambda item: (
                0 if query and query.lower() in item["label"].lower() else 1,
                -int(item["priority_score"]),
                item["label"],
            )
        )
        payload["search_results"] = search_results[:18]
        payload["view"] = "overview"
        return payload

    def _include_graph_search_result(self, node: dict[str, object]) -> bool:
        metadata = dict(node.get("metadata") or {})
        node_id = str(node.get("id") or "")
        label = str(node.get("label") or "").strip()
        kind = str(metadata.get("kind") or "node").lower()

        if not label:
            return False
        if metadata.get("is_cluster"):
            return False
        if node_id.startswith("turn-") or label.startswith("turn-"):
            return False
        if kind in {"episode", "session_turn", "workflow_state", "artifact_fallback"}:
            return False

        low_signal_prefixes = ("episode-", "artifact:", "session:", "turn:")
        if any(node_id.startswith(prefix) for prefix in low_signal_prefixes):
            return False

        return True

    def export_graph_focus(
        self,
        node_id: str,
        *,
        query: str | None = None,
        session_key: str | None = None,
        node_limit: int = 200,
        edge_limit: int = 400,
    ) -> dict[str, object]:
        if node_id.startswith("cluster:"):
            overview = self.export_graph_subgraph(
                query=query,
                session_key=session_key,
                mode="global-clustered",
                node_limit=node_limit,
                edge_limit=edge_limit,
            )
            cluster = next((item for item in overview.get("clusters", []) if str(item.get("id")) == node_id), None)
            if cluster is None:
                return {"view": "focus", "selected_id": node_id, "nodes": [], "edges": [], "message": "Cluster not found."}
            hub_payload = self.get_entity(str(cluster["hub_id"])) or {}
            member_ids = {str(item) for item in cluster.get("cluster_member_ids", [])}
            neighbor_map = {
                str(item["id"]): item
                for item in hub_payload.get("neighbors", [])
                if str(item["id"]) in member_ids or str(item["id"]) == str(cluster["hub_id"])
            }
            if str(cluster["hub_id"]) not in neighbor_map and hub_payload:
                neighbor_map[str(cluster["hub_id"])] = {
                    "id": hub_payload.get("id"),
                    "label": hub_payload.get("label"),
                    "metadata": hub_payload.get("metadata", {}),
                }
            focus_nodes = [
                {
                    "id": str(item["id"]),
                    "label": str(item["label"]),
                    "metadata": {**dict(item.get("metadata") or {}), "view_role": "focus"},
                    "degree": 0,
                    "layout": None,
                }
                for item in neighbor_map.values()
            ]
            focus_edges = [
                {
                    "source_id": str(edge["source_id"]),
                    "target_id": str(edge["target_id"]),
                    "relation": str(edge["relation"]),
                    "weight": float(edge["weight"]),
                    "metadata": dict(edge.get("metadata") or {}),
                }
                for edge in hub_payload.get("edges", [])
                if str(edge["source_id"]) in neighbor_map and str(edge["target_id"]) in neighbor_map
            ]
            return {
                "view": "focus",
                "selected_id": node_id,
                "selected_kind": "cluster",
                "nodes": focus_nodes,
                "edges": focus_edges,
                "summary": {
                    "hub_id": cluster["hub_id"],
                    "cluster_size": cluster["cluster_size"],
                    "relation_breakdown": cluster.get("relation_breakdown", {}),
                    "node_kind_breakdown": cluster.get("node_kind_breakdown", {}),
                },
                "message": f"Expanded cluster around {cluster['hub_id']}.",
            }
        entity = self.get_entity(node_id)
        if entity is None:
            return {"view": "focus", "selected_id": node_id, "nodes": [], "edges": [], "message": "Node not found."}
        focus_node_map: dict[str, dict[str, object]] = {
            str(entity["id"]): {
                "id": str(entity["id"]),
                "label": str(entity.get("label") or entity["id"]),
                "metadata": {**dict(entity.get("metadata") or {}), "view_role": "focus", "selected": True},
                "degree": len(entity.get("neighbors", [])),
                "layout": None,
            }
        }
        for neighbor in entity.get("neighbors", [])[:32]:
            focus_node_map[str(neighbor["id"])] = {
                "id": str(neighbor["id"]),
                "label": str(neighbor.get("label") or neighbor["id"]),
                "metadata": {**dict(neighbor.get("metadata") or {}), "view_role": "focus"},
                "degree": 0,
                "layout": None,
            }
        focus_edges = [
            {
                "source_id": str(edge["source_id"]),
                "target_id": str(edge["target_id"]),
                "relation": str(edge["relation"]),
                "weight": float(edge["weight"]),
                "metadata": dict(edge.get("metadata") or {}),
            }
            for edge in entity.get("edges", [])
            if str(edge["source_id"]) in focus_node_map and str(edge["target_id"]) in focus_node_map
        ]
        return {
            "view": "focus",
            "selected_id": node_id,
            "selected_kind": "node",
            "nodes": list(focus_node_map.values()),
            "edges": focus_edges,
            "summary": {
                "neighbor_count": len(entity.get("neighbors", [])),
                "edge_count": len(focus_edges),
            },
            "message": f"Focused on {node_id}.",
        }

    def export_graph_details(
        self,
        node_id: str,
        *,
        query: str | None = None,
        session_key: str | None = None,
        node_limit: int = 200,
        edge_limit: int = 400,
    ) -> dict[str, object]:
        if node_id.startswith("cluster:"):
            overview = self.export_graph_subgraph(
                query=query,
                session_key=session_key,
                mode="global-clustered",
                node_limit=node_limit,
                edge_limit=edge_limit,
            )
            cluster = next((item for item in overview.get("clusters", []) if str(item.get("id")) == node_id), None)
            if cluster is None:
                return {"view": "details", "selected_id": node_id, "error": "cluster_not_found"}
            return {
                "view": "details",
                "selected_id": node_id,
                "kind": "cluster",
                "title": str(cluster["id"]),
                "summary": f"Cluster around {cluster['hub_id']} with {cluster['cluster_size']} hidden members.",
                "metadata": {
                    "view_role": "detail",
                    "hub_id": cluster["hub_id"],
                    "cluster_size": cluster["cluster_size"],
                    "cluster_relation_types": cluster.get("cluster_relation_types", []),
                    "cluster_bridge_targets": cluster.get("cluster_bridge_targets", []),
                    "node_kind_breakdown": cluster.get("node_kind_breakdown", {}),
                    "relation_breakdown": cluster.get("relation_breakdown", {}),
                    "cluster_member_ids": cluster.get("cluster_member_ids", []),
                },
            }
        entity = self.get_entity(node_id)
        if entity is None:
            return {"view": "details", "selected_id": node_id, "error": "node_not_found"}
        metadata = dict(entity.get("metadata") or {})
        return {
            "view": "details",
            "selected_id": node_id,
            "kind": str(metadata.get("kind") or "node"),
            "title": str(entity.get("label") or node_id),
            "summary": f"{len(entity.get('neighbors', []))} neighbors, {len(entity.get('edges', []))} edges.",
            "metadata": {
                **metadata,
                "view_role": "detail",
                "related_neighbors": len(entity.get("neighbors", [])),
                "related_edges": len(entity.get("edges", [])),
            },
            "neighbors": entity.get("neighbors", [])[:24],
            "edges": entity.get("edges", [])[:32],
        }

    def _graph_priority_score(self, node: dict[str, object]) -> int:
        metadata = dict(node.get("metadata") or {})
        kind = str(metadata.get("kind") or "node")
        base = int(node.get("degree", 0) or 0)
        if metadata.get("is_cluster"):
            base += 8
        if kind == "entity":
            base += 4
        elif kind == "fact":
            base += 2
        return base

    def _focus_graph_snapshot(
        self,
        nodes: list[dict[str, object]],
        edges: list[dict[str, object]],
        *,
        focus_node: str | None,
        query: str | None,
    ) -> dict[str, list[dict[str, object]]]:
        if not nodes:
            return {"nodes": [], "edges": []}
        node_map = {str(node["id"]): node for node in nodes}
        focus_id = focus_node if focus_node in node_map else None
        if focus_id is None and query:
            query_lower = query.lower()
            for node in nodes:
                if query_lower in str(node["id"]).lower() or query_lower in str(node["label"]).lower():
                    focus_id = str(node["id"])
                    break
        if focus_id is None:
            focus_id = str(max(nodes, key=lambda item: int(item.get("degree", 0) or 0))["id"])
        neighbor_ids = {focus_id}
        filtered_edges: list[dict[str, object]] = []
        for edge in edges:
            source_id = str(edge["source_id"])
            target_id = str(edge["target_id"])
            if source_id == focus_id or target_id == focus_id:
                neighbor_ids.add(source_id)
                neighbor_ids.add(target_id)
                filtered_edges.append(edge)
        return {
            "nodes": [node_map[node_id] for node_id in neighbor_ids if node_id in node_map],
            "edges": filtered_edges,
        }

    def _cluster_graph_snapshot(
        self,
        nodes: list[dict[str, object]],
        edges: list[dict[str, object]],
    ) -> dict[str, object]:
        if not nodes or not edges:
            return {
                "nodes": nodes,
                "edges": edges,
                "clusters": [],
                "hidden_node_count": 0,
                "hidden_edge_count": 0,
            }
        node_map = {str(node["id"]): dict(node) for node in nodes}
        adjacency: dict[str, list[dict[str, object]]] = defaultdict(list)
        for edge in edges:
            adjacency[str(edge["source_id"])].append(edge)
            adjacency[str(edge["target_id"])].append(edge)
        hidden_nodes: set[str] = set()
        member_to_cluster: dict[str, str] = {}
        cluster_defs: list[dict[str, object]] = []
        hub_threshold = 8
        min_members = 5
        bridge_degree_limit = 4
        for hub in sorted(node_map.values(), key=lambda item: int(item.get("degree", 0) or 0), reverse=True):
            hub_id = str(hub["id"])
            if int(hub.get("degree", 0) or 0) < hub_threshold:
                continue
            grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
            for edge in adjacency.get(hub_id, []):
                source_id = str(edge["source_id"])
                target_id = str(edge["target_id"])
                neighbor_id = target_id if source_id == hub_id else source_id
                if neighbor_id in hidden_nodes or neighbor_id not in node_map:
                    continue
                neighbor = node_map[neighbor_id]
                neighbor_kind = str((neighbor.get("metadata") or {}).get("kind") or "node")
                direction = "out" if source_id == hub_id else "in"
                relation = str(edge["relation"])
                grouped[(direction, relation, neighbor_kind)].append(neighbor_id)
            for group_index, ((direction, relation, neighbor_kind), member_ids) in enumerate(grouped.items(), start=1):
                eligible = [
                    member_id
                    for member_id in member_ids
                    if member_id not in hidden_nodes
                    and int(node_map[member_id].get("degree", 0) or 0) <= bridge_degree_limit
                ]
                if len(eligible) < min_members:
                    continue
                cluster_id = f"cluster:{hub_id}:{direction}:{relation}:{neighbor_kind}:{group_index}"
                hidden_nodes.update(eligible)
                for member_id in eligible:
                    member_to_cluster[member_id] = cluster_id
                relation_counter = Counter()
                node_kind_counter = Counter()
                for member_id in eligible:
                    node_kind_counter[str((node_map[member_id].get("metadata") or {}).get("kind") or "node")] += 1
                    for edge in adjacency.get(member_id, []):
                        relation_counter[str(edge["relation"])] += 1
                cluster_defs.append(
                    {
                        "id": cluster_id,
                        "hub_id": hub_id,
                        "direction": direction,
                        "relation": relation,
                        "node_kind": neighbor_kind,
                        "member_ids": eligible,
                        "cluster_size": len(eligible),
                        "relation_breakdown": dict(relation_counter.most_common(6)),
                        "node_kind_breakdown": dict(node_kind_counter.most_common(6)),
                        "label": f"{relation} ×{len(eligible)}",
                    }
                )
        if not cluster_defs:
            return {
                "nodes": nodes,
                "edges": edges,
                "clusters": [],
                "hidden_node_count": 0,
                "hidden_edge_count": 0,
            }
        visible_nodes = [node for node in nodes if str(node["id"]) not in hidden_nodes]
        for cluster in cluster_defs:
            hub_node = node_map.get(str(cluster["hub_id"]))
            layout = None
            if hub_node and hub_node.get("layout"):
                hub_layout = hub_node["layout"]
                layout = {
                    "x": float(hub_layout["x"]) + 55.0,
                    "y": float(hub_layout["y"]) + 36.0,
                    "pinned": False,
                }
            visible_nodes.append(
                {
                    "id": cluster["id"],
                    "label": cluster["label"],
                    "metadata": {
                        "kind": "cluster",
                        "is_cluster": True,
                        "hub_id": cluster["hub_id"],
                        "cluster_size": cluster["cluster_size"],
                        "cluster_relation_types": [cluster["relation"]],
                        "cluster_member_ids": list(cluster["member_ids"]),
                        "cluster_relation_breakdown": cluster["relation_breakdown"],
                        "cluster_node_kind_breakdown": cluster["node_kind_breakdown"],
                        "cluster_node_kind": cluster["node_kind"],
                        "cluster_direction": cluster["direction"],
                    },
                    "degree": len(cluster["member_ids"]),
                    "layout": layout,
                }
            )
        aggregate_edges: dict[tuple[str, str, str], dict[str, object]] = {}
        hidden_edge_count = 0
        for edge in edges:
            source_id = member_to_cluster.get(str(edge["source_id"]), str(edge["source_id"]))
            target_id = member_to_cluster.get(str(edge["target_id"]), str(edge["target_id"]))
            if source_id == target_id:
                hidden_edge_count += 1
                continue
            key = (source_id, target_id, str(edge["relation"]))
            payload = aggregate_edges.get(key)
            if payload is None:
                payload = {
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation": str(edge["relation"]),
                    "weight": float(edge["weight"]),
                    "metadata": {
                        **dict(edge.get("metadata") or {}),
                        "is_aggregate": source_id.startswith("cluster:") or target_id.startswith("cluster:"),
                        "member_edge_count": 1,
                    },
                }
                aggregate_edges[key] = payload
            else:
                payload["weight"] = max(float(payload["weight"]), float(edge["weight"]))
                payload_metadata = dict(payload["metadata"])
                payload_metadata["member_edge_count"] = int(payload_metadata.get("member_edge_count", 1)) + 1
                payload["metadata"] = payload_metadata
                hidden_edge_count += 1
        cluster_bridge_targets: dict[str, set[str]] = {str(cluster["id"]): set() for cluster in cluster_defs}
        for aggregate in aggregate_edges.values():
            source_id = str(aggregate["source_id"])
            target_id = str(aggregate["target_id"])
            if source_id in cluster_bridge_targets and not target_id.startswith("cluster:"):
                cluster_bridge_targets[source_id].add(target_id)
            if target_id in cluster_bridge_targets and not source_id.startswith("cluster:"):
                cluster_bridge_targets[target_id].add(source_id)
        return {
            "nodes": visible_nodes,
            "edges": list(aggregate_edges.values()),
            "clusters": [
                {
                    "id": cluster["id"],
                    "hub_id": cluster["hub_id"],
                    "cluster_size": cluster["cluster_size"],
                    "cluster_member_ids": list(cluster["member_ids"]),
                    "cluster_relation_types": [cluster["relation"]],
                    "relation_breakdown": cluster["relation_breakdown"],
                    "node_kind_breakdown": cluster["node_kind_breakdown"],
                    "node_kind": cluster["node_kind"],
                    "direction": cluster["direction"],
                    "cluster_bridge_targets": sorted(cluster_bridge_targets.get(str(cluster["id"]), set())),
                }
                for cluster in cluster_defs
            ],
            "hidden_node_count": len(hidden_nodes),
            "hidden_edge_count": hidden_edge_count,
        }

    def _sync_graph_node(self, node_id: str) -> list[str]:
        warning = self.graph_backend.sync_node(node_id)
        return [warning] if warning else []

    def _sync_graph_edge(self, source_id: str, target_id: str, relation: str) -> list[str]:
        warning = self.graph_backend.sync_edge(source_id, target_id, relation)
        return [warning] if warning else []

    def _delete_graph_node_mirror(self, node_id: str) -> list[str]:
        warning = self.graph_backend.delete_node(node_id)
        return [warning] if warning else []

    def _delete_graph_edge_mirror(self, source_id: str, target_id: str, relation: str) -> list[str]:
        warning = self.graph_backend.delete_edge(source_id, target_id, relation)
        return [warning] if warning else []

    def upsert_graph_node(
        self,
        *,
        node_id: str,
        label: str,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        self.registry.upsert_graph_node(node_id, label=label, metadata=metadata)
        return {"node": self.get_entity(node_id), "warnings": self._sync_graph_node(node_id)}

    def delete_graph_node(self, node_id: str) -> dict[str, object]:
        self.registry.delete_graph_node(node_id)
        return {"deleted": True, "warnings": self._delete_graph_node_mirror(node_id)}

    def upsert_graph_edge(
        self,
        *,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        self.registry.upsert_graph_edge(
            source_id,
            target_id,
            relation=relation,
            weight=weight,
            metadata=metadata,
        )
        return {
            "edge": {
                "source_id": source_id,
                "target_id": target_id,
                "relation": relation,
                "weight": weight,
                "metadata": metadata,
            },
            "warnings": self._sync_graph_edge(source_id, target_id, relation),
        }

    def delete_graph_edge(self, source_id: str, target_id: str, relation: str) -> dict[str, object]:
        self.registry.delete_graph_edge(source_id, target_id, relation)
        return {"deleted": True, "warnings": self._delete_graph_edge_mirror(source_id, target_id, relation)}

    def save_graph_layouts(self, items: list[dict[str, object]]) -> dict[str, object]:
        self.registry.save_graph_layouts(items)
        return {"saved": len(items)}

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
        return artifact

    async def run_auto_summary_stage(
        self,
        session: "Session",
        *,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        turn_id: str = "",
    ) -> dict[str, object]:
        stage = "Summarizing session"
        if not self.config.auto_summarize.enabled:
            await self._emit_stage(
                on_progress,
                stage=stage,
                status="skipped",
                session_key=session.key,
                turn_id=turn_id,
                detail="skipped: disabled",
            )
            return {"status": "skipped", "artifact_id": None}
        current_tokens = int(session.metadata.get("last_prompt_tokens", 0) or session.metadata.get("estimated_context_tokens", 0) or 0)
        peak_tokens = int(session.metadata.get("max_prompt_tokens_in_turn", 0) or current_tokens)
        if current_tokens <= 0:
            await self._emit_stage(
                on_progress,
                stage=stage,
                status="not_triggered",
                session_key=session.key,
                turn_id=turn_id,
                detail="not_triggered: usage_unavailable",
            )
            return {"status": "not_triggered", "artifact_id": None}
        threshold = int(self.config.auto_summarize.max_context_tokens * self.config.auto_summarize.trigger_ratio)
        last_cutoff = int(session.metadata.get("summary_cutoff_idx", 0))
        if current_tokens < threshold:
            await self._emit_stage(
                on_progress,
                stage=stage,
                status="not_triggered",
                session_key=session.key,
                turn_id=turn_id,
                detail=f"not_triggered: last_prompt_tokens={current_tokens}, peak_prompt_tokens={peak_tokens}, threshold={threshold}",
            )
            return {"status": "not_triggered", "artifact_id": None}
        if len(session.messages) - last_cutoff < self.config.auto_summarize.min_new_messages:
            await self._emit_stage(
                on_progress,
                stage=stage,
                status="not_triggered",
                session_key=session.key,
                turn_id=turn_id,
                detail="not_triggered: not enough new messages",
            )
            return {"status": "not_triggered", "artifact_id": None}
        slice_messages = session.messages[last_cutoff:-max(1, min(6, len(session.messages)))] or session.messages[last_cutoff:]
        if not slice_messages:
            await self._emit_stage(
                on_progress,
                stage=stage,
                status="not_triggered",
                session_key=session.key,
                turn_id=turn_id,
                detail="not_triggered: empty slice",
            )
            return {"status": "not_triggered", "artifact_id": None}
        started_at = time.perf_counter()
        await self._emit_stage(
            on_progress,
            stage=stage,
            status="started",
            session_key=session.key,
            turn_id=turn_id,
            detail="Building session rollup",
        )
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
        if self.config.auto_summarize.archive_mode == "archive_continue":
            session.metadata["summary_cutoff_idx"] = max(last_cutoff, last_cutoff + len(slice_messages))
        await self._emit_stage(
            on_progress,
            stage=stage,
            status="done",
            session_key=session.key,
            turn_id=turn_id,
            detail=f"Summary artifact {artifact.id}",
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            extra={"artifact_id": artifact.id},
        )
        return {"status": "done", "artifact_id": artifact.id, "artifact": artifact}

    async def maybe_auto_summarize_session(self, session: "Session") -> MemoryArtifact | None:
        result = await self.run_auto_summary_stage(session)
        artifact = result.get("artifact")
        return artifact if isinstance(artifact, MemoryArtifact) else None

    async def _build_session_summary_text(self, session_key: str, messages: list[dict]) -> str:
        auto_role = self.app_config.resolve_model_role("auto_summarize", self.model) if self.app_config else None
        try:
            prompt_text = self.prompts.load("system/auto-summarize.md").text
        except Exception:
            prompt_text = (
                "Summarize the covered session slice with durable decisions, active threads, unresolved blockers, task outputs, and citations."
            )
        payload = "\n".join(
            f"[{msg.get('turn_id','?')}] {msg.get('role','?')}: {str(msg.get('content',''))[:500]}"
            for msg in messages
        )
        if self.auto_summarize_provider and auto_role and auto_role.model:
            try:
                response = await self.auto_summarize_provider.chat(
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

    async def prepare_shadow_context(
        self,
        user_query: str,
        session_key: str,
        channel_context: dict[str, str],
        *,
        presearch_bundle: dict[str, object] | None = None,
    ) -> ShadowBrief | None:
        return None

    def build_episode(self, session_key: str, turn_id: str, channel: str, chat_id: str, saved_entries: list[dict]) -> EpisodeRecord | None:
        return None

    async def enqueue_post_turn_ingest(self, episode: EpisodeRecord | None) -> None:
        return None

    async def run_post_turn_pipeline(
        self,
        *,
        session: "Session",
        episode: EpisodeRecord | None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> dict[str, object]:
        return {
            "file_memory": {"status": "skipped", "artifacts": 0},
            "graph": {"status": "skipped"},
            "vector": {"status": "skipped", "artifacts": 0},
            "summary": {"status": "skipped", "artifact_id": None},
        }

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
            "semantic_score": 0.0,
            "rule_score": 0.0,
            "route_confidence": 0.0,
            "route_reason": "memory unavailable",
            "query_variants": [],
            "candidate_budget": {},
            "novelty_target": 0.0,
            "store_contributions": {},
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

    async def run_auto_summary_stage(
        self,
        session: "Session",
        *,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        turn_id: str = "",
    ) -> dict[str, object]:
        return {"status": "skipped", "artifact_id": None}

    def build_runtime_context(self, session_key: str) -> str | None:
        return None

    async def rebuild_vectors(self) -> int:
        return 0

    async def rebuild_graph(self) -> int:
        return 0

    async def drain(self) -> None:
        return None

    async def analyze_node_tier(self, node_id: str, context: str = "") -> dict[str, object]:
        """Use LLM to determine tier of a node."""
        node = self.registry.get_graph_node(node_id)
        if not node:
            return {"error": "Node not found"}

        edges = self.registry.list_graph_edges(source_id=node_id) + self.registry.list_graph_edges(target_id=node_id)
        edge_count = len(edges)

        neighbors = []
        for edge in edges[:10]:
            neighbor_id = edge["target_id"] if edge["source_id"] == node_id else edge["source_id"]
            neighbor = self.registry.get_graph_node(neighbor_id)
            if neighbor:
                neighbors.append(neighbor["label"])

        prompt = f"""Analyze this knowledge graph node and determine its tier level.

Node: {node['label']}
Edges: {edge_count}
Connected to: {', '.join(neighbors[:5])}
Context: {context}

Tier 1: Main concepts (8+ edges, groups many nodes) - Examples: "Python Ecosystem", "Backend Architecture"
Tier 2: Frameworks/components (3+ edges) - Examples: "FastAPI", "PostgreSQL"
Tier 3: Details (specific facts, configs) - Examples: "FastAPI uses Pydantic"

Return JSON:
{{"tier": 1-3, "confidence": 0.0-1.0, "reason": "explanation", "parent_ids": ["suggested_parent_id"]}}"""

        if not self.provider:
            tier = 1 if edge_count >= 8 else 2 if edge_count >= 3 else 3
            return {"recommended_tier": tier, "confidence": 0.8, "reason": f"Based on {edge_count} edges", "parent_ids": []}

        response = await self.provider.generate(prompt, model=self.graph_backend.normalize_model or "fast")
        try:
            result = json.loads(response.strip())
            return {
                "recommended_tier": result.get("tier", 3),
                "confidence": result.get("confidence", 0.5),
                "reason": result.get("reason", ""),
                "parent_ids": result.get("parent_ids", [])
            }
        except:
            tier = 1 if edge_count >= 8 else 2 if edge_count >= 3 else 3
            return {"recommended_tier": tier, "confidence": 0.6, "reason": "Fallback heuristic", "parent_ids": []}

    async def reorganize_node_hierarchy(self, node_id: str, new_tier: int, new_parent_ids: list[str] | None = None) -> dict[str, object]:
        """Move node to different tier and update parent relationships."""
        node = self.registry.get_graph_node(node_id)
        if not node:
            return {"error": "Node not found"}

        old_tier = node.get("tier", 3)
        metadata = json.loads(node.get("metadata_json", "{}"))
        metadata["tier"] = new_tier
        metadata["tier_reason"] = f"Reorganized from tier {old_tier} to tier {new_tier}"
        metadata["last_tier_update"] = datetime.utcnow().isoformat()

        self.registry.upsert_graph_node(node_id, node["label"], metadata, tier=new_tier)

        old_parents = self.registry.list_graph_edges(target_id=node_id, relation="parent_of")
        for edge in old_parents:
            self.registry.delete_graph_edge(edge["source_id"], node_id, "parent_of")

        if new_parent_ids:
            for parent_id in new_parent_ids:
                self.registry.upsert_graph_edge(parent_id, node_id, "parent_of", weight=1.0, metadata={})

        return {"status": "success", "old_tier": old_tier, "new_tier": new_tier, "parent_count": len(new_parent_ids or [])}

    def traverse_hierarchy(self, start_node_id: str, direction: str = "both", max_depth: int = 3) -> dict[str, object]:
        """Traverse graph hierarchy from a starting node."""
        return self.graph_backend.traverse_hierarchy(start_node_id, direction, max_depth)

    def close(self) -> None:
        return None
