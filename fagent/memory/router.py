"""Query-aware memory routing."""

from __future__ import annotations

from dataclasses import dataclass, field

from fagent.memory.types import MemorySearchRequestV2
from fagent.providers.base import LLMProvider


@dataclass(slots=True)
class MemoryRoute:
    """Routed retrieval plan."""

    intent: str
    recommended_stores: list[str]
    artifact_type_bias: list[str] = field(default_factory=list)
    allow_raw_escalation: bool = False
    target_top_k: int = 6
    strategy: str = "balanced"
    confidence: float = 0.7


class MemoryRouter:
    """Deterministic query classifier with optional light-LLM refinement hook."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        model: str | None = None,
        default_strategy: str = "balanced",
        raw_evidence_escalation: bool = True,
    ):
        self.provider = provider
        self.model = model
        self.default_strategy = default_strategy
        self.raw_evidence_escalation = raw_evidence_escalation

    async def route(
        self,
        query: str,
        session_key: str,
        *,
        active_task_state: str | None = None,
        recent_workflow_state: str | None = None,
    ) -> MemoryRoute:
        text = query.lower().strip()
        intent = "fresh_request"
        stores = ["file", "vector", "graph"]
        artifact_types: list[str] = []
        allow_raw = False
        top_k = 6

        if any(token in text for token in ("вчера", "сегодня", "yesterday", "today", "когда", "что я просил")):
            intent = "temporal_recall"
            stores = ["file", "vector", "graph"]
            artifact_types = ["daily_note", "session_turn", "session_summary"]
            allow_raw = True
        elif any(token in text for token in ("как связано", "связаны", "relationship", "relates", "почему связано")):
            intent = "relationship_recall"
            stores = ["graph", "file", "vector"]
            artifact_types = ["task_state", "entity", "relationship", "fact"]
        elif any(
            token in text
            for token in (
                "что ты делал",
                "workflow",
                "step",
                "шаг",
                "ошиб",
                "blocker",
                "сломал",
                "почему embeddings",
                "почему эмбед",
            )
        ):
            intent = "workflow_recall"
            stores = ["graph", "file", "vector"]
            artifact_types = ["workflow_state", "task_state", "task_step", "experience_pattern"]
            allow_raw = True
        elif any(token in text for token in ("какой стек", "что решили", "decision", "fact", "remember", "вспомни")):
            intent = "factual_recall"
            stores = ["file", "graph", "vector"]
            artifact_types = ["fact", "summary_note", "session_summary"]
            allow_raw = self.raw_evidence_escalation
        elif any(token in text for token in ("предпочита", "preference", "любишь", "предпочт")):
            intent = "preference_recall"
            stores = ["file", "vector", "graph"]
            artifact_types = ["fact", "experience_pattern"]
        elif any(token in text for token in ("продолж", "continue", "continuity", "контекст проекта", "что у нас сейчас")):
            intent = "continuity"
            stores = ["file", "graph", "vector"]
            artifact_types = ["session_summary", "task_state", "summary_note", "fact"]
        elif any(token in text for token in ("обобщ", "summary", "synthesis", "синтез", "overview")):
            intent = "broad_synthesis"
            stores = ["file", "graph", "vector"]
            artifact_types = ["session_summary", "summary_note", "workflow_state"]
            top_k = 8
        elif active_task_state or recent_workflow_state:
            intent = "continuity"
            stores = ["graph", "file", "vector"]
            artifact_types = ["task_state", "workflow_state", "session_summary"]

        return MemoryRoute(
            intent=intent,
            recommended_stores=stores,
            artifact_type_bias=artifact_types,
            allow_raw_escalation=allow_raw,
            target_top_k=top_k,
            strategy=self.default_strategy,
            confidence=0.8 if intent != "fresh_request" else 0.4,
        )

    async def build_request(
        self,
        query: str,
        session_key: str,
        *,
        strategy: str | None = None,
        active_task_state: str | None = None,
        recent_workflow_state: str | None = None,
    ) -> MemorySearchRequestV2:
        route = await self.route(
            query,
            session_key,
            active_task_state=active_task_state,
            recent_workflow_state=recent_workflow_state,
        )
        return MemorySearchRequestV2(
            query=query,
            intent=route.intent,
            strategy=strategy or route.strategy,
            stores=route.recommended_stores,
            artifact_types=route.artifact_type_bias,
            session_scope=session_key,
            allow_raw_escalation=route.allow_raw_escalation,
        )
