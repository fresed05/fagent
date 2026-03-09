"""Memory search tools exposed to the main agent."""

from __future__ import annotations

import json
from typing import Any

from fagent.agent.tools.base import Tool
from fagent.memory.orchestrator import MemoryOrchestrator, NullMemoryOrchestrator
from fagent.prompts import PromptLoader


class MemorySearchTool(Tool):
    """Explicit memory search across file, vector, and graph stores."""

    def __init__(self, memory: MemoryOrchestrator | NullMemoryOrchestrator):
        self.memory = memory
        self.prompts = PromptLoader.from_package()

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "Search file, vector, and graph memory for prior context or evidence."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2},
                "stores": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["file", "vector", "graph", "all"]},
                },
                "artifact_types": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                "session_scope": {"type": "string"},
                "time_range": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                    },
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        stores: list[str] | None = None,
        artifact_types: list[str] | None = None,
        top_k: int = 5,
        session_scope: str | None = None,
        time_range: dict[str, str] | None = None,
    ) -> str:
        payload = await self.memory.search_v2(
            query,
            stores=None if not stores or "all" in stores else stores,
            artifact_types=artifact_types,
            top_k=top_k,
            session_scope=session_scope,
            time_range=time_range,
        )
        return json.dumps(
            {
                "query": query,
                "intent": payload["intent"],
                "retrieval_strategy": payload["retrieval_strategy"],
                "confidence": payload["confidence"],
                "used_stores": payload["used_stores"],
                "raw_escalated": payload["raw_escalated"],
                "count": payload["count"],
                "citations": payload["citations"],
                "results": [
                    {
                        "artifact_id": item.artifact_id,
                        "store": item.store,
                        "score": round(item.score, 4),
                        "snippet": item.snippet,
                        "reason": item.reason,
                        "metadata": item.metadata,
                    }
                    for item in payload["results"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )


class MemorySearchV2Tool(Tool):
    """Query-aware memory search with routing and evidence escalation."""

    def __init__(self, memory: MemoryOrchestrator | NullMemoryOrchestrator):
        self.memory = memory

    @property
    def name(self) -> str:
        return "memory_search_v2"

    @property
    def description(self) -> str:
        return "Search memory using query-aware routing, intent detection, and optional raw evidence escalation."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2},
                "strategy": {"type": "string", "enum": ["cheap", "balanced", "evidence_first"]},
                "stores": {"type": "array", "items": {"type": "string"}},
                "artifact_types": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                "session_scope": {"type": "string"},
                "time_range": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                    },
                },
                "allow_raw_escalation": {"type": "boolean"},
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        strategy: str = "balanced",
        stores: list[str] | None = None,
        artifact_types: list[str] | None = None,
        top_k: int = 6,
        session_scope: str | None = None,
        time_range: dict[str, str] | None = None,
        allow_raw_escalation: bool = False,
    ) -> str:
        selected = None if not stores or "all" in stores else stores
        payload = await self.memory.search_v2(
            query,
            strategy=strategy,
            stores=selected,
            artifact_types=artifact_types,
            top_k=top_k,
            session_scope=session_scope,
            time_range=time_range,
            allow_raw_escalation=allow_raw_escalation,
        )
        return json.dumps(
            {
                "query": query,
                "intent": payload["intent"],
                "retrieval_strategy": payload["retrieval_strategy"],
                "confidence": payload["confidence"],
                "used_stores": payload["used_stores"],
                "raw_escalated": payload["raw_escalated"],
                "count": payload["count"],
                "citations": payload["citations"],
                "results": [
                {
                    "artifact_id": item.artifact_id,
                    "store": item.store,
                    "score": round(item.score, 4),
                    "snippet": item.snippet,
                    "reason": item.reason,
                    "metadata": item.metadata,
                }
                    for item in payload["results"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )


class MemoryGetArtifactTool(Tool):
    """Fetch a concrete memory artifact by id."""

    def __init__(self, memory: MemoryOrchestrator | NullMemoryOrchestrator):
        self.memory = memory

    @property
    def name(self) -> str:
        return "memory_get_artifact"

    @property
    def description(self) -> str:
        return "Load a stored memory artifact by artifact id."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string", "minLength": 2},
            },
            "required": ["artifact_id"],
        }

    async def execute(self, artifact_id: str) -> str:
        artifact = self.memory.get_artifact(artifact_id)
        if artifact is None:
            return json.dumps({"status": "not_found", "artifact_id": artifact_id}, ensure_ascii=False, indent=2)
        return json.dumps(
            {
                "status": "ok",
                "artifact": {
                    "id": artifact.id,
                    "type": artifact.type,
                    "content": artifact.content,
                    "summary": artifact.summary,
                    "metadata": artifact.metadata,
                    "source_ref": artifact.source_ref,
                    "created_at": artifact.created_at,
                },
            },
            ensure_ascii=False,
            indent=2,
        )


class MemoryGetEntityTool(Tool):
    """Fetch a graph entity or fact with its local neighborhood."""

    def __init__(self, memory: MemoryOrchestrator | NullMemoryOrchestrator):
        self.memory = memory

    @property
    def name(self) -> str:
        return "memory_get_entity"

    @property
    def description(self) -> str:
        return "Load a graph entity or fact by id or fuzzy label match."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_ref": {"type": "string", "minLength": 2},
            },
            "required": ["entity_ref"],
        }

    async def execute(self, entity_ref: str) -> str:
        entity = self.memory.get_entity(entity_ref)
        if entity is None:
            return json.dumps({"status": "not_found", "entity_ref": entity_ref}, ensure_ascii=False, indent=2)
        return json.dumps({"status": "ok", "entity": entity}, ensure_ascii=False, indent=2)


class MemoryGetDailyNoteTool(Tool):
    """Load one daily note file by ISO date."""

    def __init__(self, memory: MemoryOrchestrator | NullMemoryOrchestrator):
        self.memory = memory

    @property
    def name(self) -> str:
        return "memory_get_daily_note"

    @property
    def description(self) -> str:
        return "Load a daily note by date in YYYY-MM-DD format."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {"type": "string", "minLength": 10, "maxLength": 10},
            },
            "required": ["date"],
        }

    async def execute(self, date: str) -> str:
        note = self.memory.get_daily_note(date)
        if note is None:
            return json.dumps({"status": "not_found", "date": date}, ensure_ascii=False, indent=2)
        return json.dumps({"status": "ok", "note": note}, ensure_ascii=False, indent=2)
