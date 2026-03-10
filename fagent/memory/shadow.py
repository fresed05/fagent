"""Adaptive shadow context builder."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any

from fagent.memory.types import RetrievedMemory, SessionShadowState, ShadowBrief


def _token_set(text: str) -> set[str]:
    return {token for token in (text or "").lower().split() if len(token) > 2}


def _overlap(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


@dataclass(slots=True)
class ShadowContextBuilder:
    """Build compact, turn-aware shadow briefs from routed evidence."""

    max_tokens: int = 400
    session_history: dict[str, SessionShadowState] = field(default_factory=dict)

    def _mmr_select(
        self,
        candidates: list[RetrievedMemory],
        *,
        limit: int,
        recent_citations: set[str],
    ) -> list[RetrievedMemory]:
        selected: list[RetrievedMemory] = []
        pool = list(candidates)
        while pool and len(selected) < limit:
            best_item: RetrievedMemory | None = None
            best_score = float("-inf")
            for item in pool:
                repeat_penalty = 0.12 if item.artifact_id in recent_citations else 0.0
                redundancy = max((_overlap(item.snippet, picked.snippet) for picked in selected), default=0.0)
                score = item.score - 0.18 * redundancy - repeat_penalty
                if best_item is None or score > best_score:
                    best_item = item
                    best_score = score
            assert best_item is not None
            selected.append(best_item)
            pool = [item for item in pool if item.artifact_id != best_item.artifact_id]
        return selected

    def _working_set_items(self, working_set: dict[str, Any]) -> tuple[list[str], list[str]]:
        anchors: list[str] = []
        open_items: list[str] = []
        active_task = str(working_set.get("active_task_state") or "").strip()
        if active_task:
            anchors.append(active_task[:220])
        for decision in working_set.get("current_decisions", [])[:2]:
            anchors.append(str(decision)[:220])
        for blocker in working_set.get("open_blockers", [])[:2]:
            open_items.append(str(blocker)[:220])
        return anchors[:2], open_items[:2]

    async def build(
        self,
        user_query: str,
        session_key: str,
        channel_context: dict[str, str],
        *,
        evidence_bundle: dict[str, Any] | None = None,
        working_set: dict[str, Any] | None = None,
    ) -> ShadowBrief:
        routed = evidence_bundle or {}
        all_results = list(routed.get("results", []))
        if not all_results:
            return ShadowBrief(
                summary="No relevant memory retrieved.",
                facts=[],
                open_questions=[],
                citations=[],
                confidence=0.0,
                store_breakdown={},
                raw_results=[],
            )

        history = self.session_history.setdefault(session_key, SessionShadowState())
        recent_citations = {
            citation
            for window in history.recent_citation_windows[-3:]
            for citation in window
        }
        working_set = working_set or {}
        anchor_items = [item for item in all_results if item.artifact_id in set(history.last_anchor_ids)]
        changed_items = [
            item for item in all_results
            if item.metadata.get("superseded")
            or "contradict" in item.reason.lower()
            or "changed" in item.reason.lower()
        ]
        open_items_from_results = [
            item for item in all_results
            if item.metadata.get("status") in {"open", "blocked", "in_progress"}
            or item.metadata.get("node_type") == "blocker"
            or item.metadata.get("open_blockers")
        ]
        stable_anchors = self._mmr_select(anchor_items or all_results, limit=2, recent_citations=set())
        excluded = {item.artifact_id for item in stable_anchors}
        novel_pool = [item for item in all_results if item.artifact_id not in excluded]
        novel_items = self._mmr_select(novel_pool, limit=2, recent_citations=recent_citations)

        state_lines, working_open_items = self._working_set_items(working_set)
        anchor_lines = state_lines or [item.snippet.replace("\n", " ")[:180] for item in stable_anchors]
        fact_lines = [item.snippet.replace("\n", " ")[:180] for item in novel_items] or [
            item.snippet.replace("\n", " ")[:180] for item in stable_anchors[:2]
        ]
        changed_lines = [item.snippet.replace("\n", " ")[:180] for item in changed_items[:1]]
        open_lines = working_open_items[:]
        for item in open_items_from_results[:2]:
            text = item.snippet.replace("\n", " ")[:180]
            if text not in open_lines:
                open_lines.append(text)

        chosen_results = stable_anchors + [item for item in novel_items if item.artifact_id not in excluded]
        if changed_items:
            for item in changed_items[:1]:
                if item.artifact_id not in {picked.artifact_id for picked in chosen_results}:
                    chosen_results.append(item)
        chosen_results = chosen_results[:6]

        citations = [item.artifact_id for item in chosen_results[:6]]
        store_breakdown: dict[str, int] = {}
        for item in chosen_results:
            store_breakdown[item.store] = store_breakdown.get(item.store, 0) + 1

        summary_parts: list[str] = []
        lead_snippet = chosen_results[0].snippet.replace("\n", " ")[:120] if chosen_results else ""
        if anchor_lines:
            summary_parts.append(lead_snippet or "Current state anchored in active session memory.")
        if fact_lines:
            summary_parts.append(f"{len(fact_lines)} relevant memory items selected.")
        if changed_lines:
            summary_parts.append("Recent change or contradiction detected.")
        if open_lines:
            summary_parts.append("Open blockers or unresolved items remain.")
        summary = " ".join(summary_parts)[:280] or "Adaptive shadow memory bundle."
        confidence = float(routed.get("confidence", 0.0))
        fingerprint = hashlib.sha1(
            "\n".join([user_query, *anchor_lines, *fact_lines, *changed_lines, *citations]).encode("utf-8")
        ).hexdigest()[:16]

        history.last_query = user_query
        history.last_citations = citations
        history.last_anchor_ids = [item.artifact_id for item in stable_anchors]
        history.last_brief_fingerprint = fingerprint
        history.recent_citation_windows.append(citations)
        history.recent_citation_windows = history.recent_citation_windows[-3:]

        return ShadowBrief(
            summary=summary,
            facts=anchor_lines + fact_lines,
            open_questions=open_lines,
            citations=citations,
            confidence=confidence,
            contradictions=changed_lines,
            retrieval_strategy=str(routed.get("retrieval_strategy", "adaptive")),
            store_breakdown=store_breakdown,
            raw_results=chosen_results,
            current_state=anchor_lines[:2],
            relevant_facts=fact_lines[:2],
            open_items=open_lines[:2],
            what_changed=changed_lines[:1],
        )
