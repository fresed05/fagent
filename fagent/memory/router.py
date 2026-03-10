"""Hybrid semantic + heuristic memory routing."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any

from fagent.memory.types import MemorySearchRequestV2
from fagent.memory.vector import _cosine_similarity
from fagent.providers.base import LLMProvider


_INTENT_PROTOTYPES: dict[str, list[str]] = {
    "temporal_recall": [
        "what happened yesterday",
        "what did we do today",
        "when did we discuss this",
        "что было вчера",
        "что мы делали сегодня",
        "когда мы это обсуждали",
        "what changed since last turn",
        "что ты делал раньше",
    ],
    "relationship_recall": [
        "how is this related",
        "what connects these entities",
        "dependency between services",
        "как это связано",
        "что связывает эти сущности",
        "зависимость между сервисами",
        "relation between x and y",
        "graph relation lookup",
    ],
    "workflow_recall": [
        "what steps did you take",
        "why did this fail",
        "what blocker did we hit",
        "workflow status",
        "какие шаги ты делал",
        "почему это сломалось",
        "какой был блокер",
        "состояние воркфлоу",
    ],
    "factual_recall": [
        "what do you remember about this",
        "what was decided",
        "recall the fact",
        "technical fact lookup",
        "что ты помнишь об этом",
        "что решили",
        "вспомни факт",
        "какой стек выбрали",
    ],
    "preference_recall": [
        "what do i prefer",
        "preferred stack",
        "which style do i like",
        "мои предпочтения",
        "какой стек я предпочитаю",
        "что я люблю использовать",
        "preferred workflow",
        "my usual preference",
    ],
    "continuity": [
        "where are we now",
        "continue the current task",
        "current context of the project",
        "what is the current state",
        "что у нас сейчас",
        "продолжай текущую задачу",
        "текущий контекст проекта",
        "на чем мы остановились",
    ],
    "broad_synthesis": [
        "summarize everything relevant",
        "give me the overview",
        "synthesize the project state",
        "общая сводка",
        "суммируй все важное",
        "дай обзор по проекту",
        "широкий синтез по теме",
        "high level overview",
    ],
    "fresh_request": [
        "implement a new feature",
        "do a new task",
        "start from scratch",
        "сделай новую задачу",
        "начни новую работу",
        "новый запрос без памяти",
        "fresh user request",
        "new unrelated task",
    ],
}

_INTENT_STORE_MAP: dict[str, list[str]] = {
    "temporal_recall": ["file", "graph", "vector"],
    "relationship_recall": ["graph", "file", "vector"],
    "workflow_recall": ["workflow", "task_graph", "graph", "file", "experience", "vector"],
    "factual_recall": ["file", "graph", "vector", "experience"],
    "preference_recall": ["file", "vector", "graph", "experience"],
    "continuity": ["summary", "task_graph", "workflow", "graph", "file"],
    "broad_synthesis": ["summary", "file", "graph", "vector", "task_graph"],
    "fresh_request": ["file", "graph", "vector"],
}

_INTENT_ARTIFACT_MAP: dict[str, list[str]] = {
    "temporal_recall": ["daily_note", "summary_note", "session_turn", "session_summary"],
    "relationship_recall": ["entity", "relationship", "fact", "task_state"],
    "workflow_recall": ["workflow_state", "task_state", "task_step", "experience_pattern", "session_turn"],
    "factual_recall": ["fact", "summary_note", "daily_note", "session_turn", "session_summary"],
    "preference_recall": ["fact", "experience_pattern"],
    "continuity": ["session_summary", "task_state", "workflow_state", "fact", "summary_note", "daily_note", "session_turn"],
    "broad_synthesis": ["session_summary", "summary_note", "daily_note", "workflow_state", "fact", "session_turn"],
    "fresh_request": [],
}

_INTENT_BUDGETS: dict[str, dict[str, int]] = {
    "relationship_recall": {"graph": 12, "file": 8, "vector": 6, "task_graph": 6, "final": 6},
    "workflow_recall": {"workflow": 6, "task_graph": 6, "graph": 8, "file": 8, "experience": 5, "vector": 5, "final": 7},
    "factual_recall": {"file": 10, "graph": 10, "vector": 8, "experience": 4, "final": 6},
    "continuity": {"summary": 4, "task_graph": 6, "workflow": 5, "graph": 8, "file": 8, "final": 6},
    "broad_synthesis": {"summary": 4, "file": 10, "graph": 10, "vector": 8, "task_graph": 5, "final": 8},
    "temporal_recall": {"file": 10, "graph": 8, "vector": 6, "final": 6},
    "preference_recall": {"file": 8, "vector": 8, "graph": 6, "experience": 4, "final": 6},
    "fresh_request": {"file": 5, "graph": 5, "vector": 4, "final": 4},
}

_INTENT_NOVELTY: dict[str, float] = {
    "continuity": 0.22,
    "workflow_recall": 0.28,
    "relationship_recall": 0.26,
    "broad_synthesis": 0.34,
    "fresh_request": 0.18,
}

_RULE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "temporal_recall": ("вчера", "сегодня", "когда", "yesterday", "today", "when did", "last time"),
    "relationship_recall": ("связ", "relationship", "related", "depends", "dependency", "graph"),
    "workflow_recall": ("шаг", "workflow", "blocker", "слом", "ошиб", "step", "failed", "why did"),
    "factual_recall": ("что ты помнишь", "remember", "решили", "fact", "recall", "stack"),
    "preference_recall": ("предпоч", "prefer", "favorite", "любишь", "обычно использу"),
    "continuity": ("продолж", "continue", "сейчас", "current state", "where are we", "context"),
    "broad_synthesis": ("summary", "overview", "synthesis", "обзор", "сводк", "сумм"),
}


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
    semantic_score: float = 0.0
    rule_score: float = 0.0
    route_confidence: float = 0.0
    route_reason: str = ""
    query_variants: list[str] = field(default_factory=list)
    candidate_budget: dict[str, int] = field(default_factory=dict)
    novelty_target: float = 0.2


class MemoryRouter:
    """Hybrid semantic router with deterministic rule fallback."""

    _PROTOTYPE_CACHE: dict[str, tuple[dict[str, list[float]], dict[str, list[list[float]]]]] = {}

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        model: str | None = None,
        default_strategy: str = "balanced",
        raw_evidence_escalation: bool = True,
        embedder: Any | None = None,
    ):
        self.provider = provider
        self.model = model
        self.default_strategy = default_strategy
        self.raw_evidence_escalation = raw_evidence_escalation
        self.embedder = embedder
        self._prototype_centroids: dict[str, list[float]] = {}
        self._prototype_vectors: dict[str, list[list[float]]] = {}
        self._prototype_ready = False

    @staticmethod
    def _normalize(text: str) -> str:
        cleaned = unicodedata.normalize("NFKC", text or "").strip().lower()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    @staticmethod
    def _englishish(text: str) -> str:
        text = MemoryRouter._normalize(text)
        text = re.sub(r"[^\w\s:/.-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _query_embedding(self, text: str) -> list[float]:
        if self.embedder is not None and hasattr(self.embedder, "embed_query"):
            try:
                return self.embedder.embed_query(text)
            except Exception:
                return []
        client = getattr(self.embedder, "embedding_client", None)
        if client is None:
            return []
        try:
            return client.embed_texts([text])[0]
        except Exception:
            return []

    def _ensure_prototypes(self) -> None:
        if self._prototype_ready:
            return
        client = getattr(self.embedder, "embedding_client", None)
        if client is None:
            self._prototype_ready = True
            return
        cache_key = getattr(client, "embedding_version", "")
        if cache_key and cache_key in self._PROTOTYPE_CACHE:
            centroids, vectors = self._PROTOTYPE_CACHE[cache_key]
            self._prototype_centroids = {intent: list(values) for intent, values in centroids.items()}
            self._prototype_vectors = {
                intent: [list(vector) for vector in items]
                for intent, items in vectors.items()
            }
            self._prototype_ready = True
            return
        for intent, exemplars in _INTENT_PROTOTYPES.items():
            try:
                vectors = client.embed_texts(exemplars)
            except Exception:
                self._prototype_ready = True
                return
            if not vectors:
                continue
            self._prototype_vectors[intent] = vectors
            dims = len(vectors[0])
            centroid = [0.0] * dims
            for vector in vectors:
                for idx, value in enumerate(vector):
                    centroid[idx] += value
            self._prototype_centroids[intent] = [value / len(vectors) for value in centroid]
        if cache_key and self._prototype_centroids:
            self._PROTOTYPE_CACHE[cache_key] = (
                {intent: list(values) for intent, values in self._prototype_centroids.items()},
                {intent: [list(vector) for vector in values] for intent, values in self._prototype_vectors.items()},
            )
        self._prototype_ready = True

    def _semantic_scores(self, query: str) -> tuple[dict[str, float], list[float]]:
        self._ensure_prototypes()
        query_vector = self._query_embedding(query)
        if not query_vector or not self._prototype_centroids:
            return ({intent: 0.0 for intent in _INTENT_PROTOTYPES}, [])
        scores: dict[str, float] = {}
        for intent, centroid in self._prototype_centroids.items():
            centroid_score = max(0.0, _cosine_similarity(query_vector, centroid))
            exemplar_score = max(
                (_cosine_similarity(query_vector, vector) for vector in self._prototype_vectors.get(intent, [])),
                default=0.0,
            )
            scores[intent] = max(centroid_score, 0.95 * exemplar_score)
        return scores, query_vector

    def _rule_scores(
        self,
        query: str,
        *,
        active_task_state: str | None = None,
        recent_workflow_state: str | None = None,
    ) -> dict[str, float]:
        normalized = self._normalize(query)
        scores = {intent: 0.0 for intent in _INTENT_PROTOTYPES}
        for intent, keywords in _RULE_KEYWORDS.items():
            hits = sum(1 for keyword in keywords if keyword in normalized)
            if hits:
                scores[intent] = min(1.0, 0.34 + 0.18 * hits)
        if active_task_state or recent_workflow_state:
            scores["continuity"] = max(scores["continuity"], 0.55)
        if normalized.count(" ") < 2:
            scores["fresh_request"] = max(scores["fresh_request"], 0.25)
        return scores

    def _default_variants(self, query: str) -> list[str]:
        normalized = self._englishish(query)
        variants: list[str] = []
        if normalized and normalized != self._normalize(query):
            variants.append(normalized)
        if len(normalized.split()) <= 3:
            squashed = normalized.replace(" ", "")
            if squashed and squashed not in variants and squashed != normalized:
                variants.append(squashed)
        return variants[:2]

    async def route(
        self,
        query: str,
        session_key: str,
        *,
        active_task_state: str | None = None,
        recent_workflow_state: str | None = None,
    ) -> MemoryRoute:
        semantic_scores, _query_vector = self._semantic_scores(query)
        rule_scores = self._rule_scores(
            query,
            active_task_state=active_task_state,
            recent_workflow_state=recent_workflow_state,
        )
        final_scores: dict[str, float] = {}
        for intent in _INTENT_PROTOTYPES:
            semantic = semantic_scores.get(intent, 0.0)
            rule = rule_scores.get(intent, 0.0)
            weight = 0.75 if self._prototype_centroids else 0.0
            final_scores[intent] = weight * semantic + (1.0 - weight) * rule if self._prototype_centroids else rule
            if self._prototype_centroids:
                final_scores[intent] = 0.75 * semantic + 0.25 * rule

        intent, confidence = max(final_scores.items(), key=lambda item: item[1], default=("fresh_request", 0.0))
        semantic_score = semantic_scores.get(intent, 0.0)
        rule_score = rule_scores.get(intent, 0.0)
        low_confidence = confidence < 0.48
        route_intent = intent if not low_confidence else "fresh_request"
        stores = list(_INTENT_STORE_MAP.get(route_intent, _INTENT_STORE_MAP["fresh_request"]))
        strategy = self.default_strategy if not low_confidence else "balanced"
        if low_confidence:
            stores = ["file", "graph", "vector"]
        query_variants = self._default_variants(query)
        route_reason = (
            f"hybrid semantic={semantic_score:.2f} rule={rule_score:.2f}"
            if self._prototype_centroids
            else f"rule fallback={rule_score:.2f}"
        )
        if low_confidence:
            route_reason += "; low confidence fallback to balanced retrieval"

        return MemoryRoute(
            intent=route_intent,
            recommended_stores=stores,
            artifact_type_bias=list(_INTENT_ARTIFACT_MAP.get(route_intent, [])),
            allow_raw_escalation=self.raw_evidence_escalation or route_intent in {"temporal_recall", "workflow_recall"},
            target_top_k=_INTENT_BUDGETS.get(route_intent, {}).get("final", 6),
            strategy=strategy,
            confidence=max(confidence, 0.12 if query.strip() else 0.0),
            semantic_score=semantic_score,
            rule_score=rule_score,
            route_confidence=max(confidence, 0.12 if query.strip() else 0.0),
            route_reason=route_reason,
            query_variants=query_variants,
            candidate_budget=dict(_INTENT_BUDGETS.get(route_intent, _INTENT_BUDGETS["fresh_request"])),
            novelty_target=_INTENT_NOVELTY.get(route_intent, 0.2),
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
            semantic_score=route.semantic_score,
            rule_score=route.rule_score,
            route_confidence=route.route_confidence,
            route_reason=route.route_reason,
            query_variants=route.query_variants,
            candidate_budget=route.candidate_budget,
            novelty_target=route.novelty_target,
        )
