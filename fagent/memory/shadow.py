"""Shadow context builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from fagent.prompts import PromptLoader
from fagent.memory.types import RetrievedMemory, ShadowBrief
from fagent.providers.base import LLMProvider


class RetrievalBackend(Protocol):
    """Minimal protocol shared by memory backends used in shadow retrieval."""

    def retrieve(self, query: str, limit: int = 5) -> list[RetrievedMemory]:
        """Return retrieved memory snippets."""


@dataclass(slots=True)
class ShadowContextBuilder:
    """Retrieve and compress memory before the main model runs."""

    backends: list[tuple[str, RetrievalBackend]]
    provider: LLMProvider | None = None
    fast_model: str | None = None
    max_tokens: int = 400
    prompt_loader: PromptLoader | None = None

    async def build(self, user_query: str, session_key: str, channel_context: dict[str, str]) -> ShadowBrief:
        """Build a compact shadow brief from available memory stores."""
        all_results: list[RetrievedMemory] = []
        for _, backend in self.backends:
            try:
                all_results.extend(backend.retrieve(user_query))
            except Exception as exc:
                logger.warning("Shadow retrieval backend failed: {}", exc)
        all_results.sort(key=lambda item: item.score, reverse=True)
        top_results = all_results[:8]
        if not top_results:
            return ShadowBrief(
                summary="No relevant memory retrieved.",
                facts=[],
                open_questions=[],
                citations=[],
                confidence=0.0,
                store_breakdown={},
                raw_results=[],
            )

        confidence = min(1.0, sum(item.score for item in top_results[:3]) / 3)
        store_breakdown: dict[str, int] = {}
        contradictions = [
            f"{item.artifact_id}: {item.reason}" for item in top_results
            if "contradict" in item.reason.lower() or item.metadata.get("superseded")
        ]
        for item in top_results:
            store_breakdown[item.store] = store_breakdown.get(item.store, 0) + 1
        if self.provider and self.fast_model:
            prompt = "\n\n".join(
                f"[{item.store}] {item.snippet}\nReason: {item.reason}"
                for item in top_results[:6]
            )
            try:
                system_prompt = (
                    self.prompt_loader.load("system/shadow-context.md").text
                    if self.prompt_loader
                    else (
                        "Compress retrieved memory into 3 sections: Summary, Facts, Open Questions. "
                        "Use concise bullets and do not answer the user directly."
                    )
                )
                response = await self.provider.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": (
                                f"User query: {user_query}\n"
                                f"Session: {session_key}\n"
                                f"Channel context: {channel_context}\n\n"
                                f"Retrieved memory:\n{prompt}"
                            ),
                        },
                    ],
                    model=self.fast_model,
                    max_tokens=self.max_tokens,
                    temperature=0.1,
                )
                if response.content:
                    return ShadowBrief(
                        summary=response.content.strip(),
                        facts=[item.snippet for item in top_results[:3]],
                        open_questions=[] if confidence >= 0.35 else ["Memory confidence is low; verify against the current user request."],
                        citations=[item.artifact_id for item in top_results[:5]],
                        confidence=confidence,
                        contradictions=contradictions,
                        retrieval_strategy="direct+fast-model",
                        store_breakdown=store_breakdown,
                        raw_results=top_results,
                    )
            except Exception as exc:
                logger.warning("Shadow fast-model summarization failed: {}", exc)

        facts = [item.snippet for item in top_results[:3]]
        open_questions = []
        if confidence < 0.35:
            open_questions.append("Retrieved memory is weak or fragmented; prefer the current user message over recalled context.")
        summary = " | ".join(item.snippet.replace("\n", " ")[:160] for item in top_results[:3])
        return ShadowBrief(
            summary=summary,
            facts=facts,
            open_questions=open_questions,
            citations=[item.artifact_id for item in top_results[:5]],
            confidence=confidence,
            contradictions=contradictions,
            retrieval_strategy="direct",
            store_breakdown=store_breakdown,
            raw_results=top_results,
        )
