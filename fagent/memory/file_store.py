"""Explicit file memory storage for operator-authored notes."""

from __future__ import annotations

import re
from pathlib import Path

from fagent.memory.types import EpisodeRecord, MemoryArtifact, RetrievedMemory
from fagent.utils.helpers import ensure_dir


class FileMemoryStore:
    """Markdown memory files managed explicitly by the main agent."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    def ingest_episode(self, episode: EpisodeRecord, summary: str | None = None) -> list[MemoryArtifact]:
        del episode, summary
        return []

    def retrieve(self, query: str, limit: int = 5) -> list[RetrievedMemory]:
        query_lower = query.lower()
        normalized_query = self._normalize_text(query)
        compact_query = self._compact_text(query)
        query_tokens = self._query_tokens(query)
        results: list[RetrievedMemory] = []
        candidates = self._candidate_files()
        for path in candidates:
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            lower_content = content.lower()
            normalized_content = self._normalize_text(content)
            compact_content = self._compact_text(content)

            exact_match = query_lower in lower_content
            compact_match = compact_query and compact_query in compact_content
            token_overlap = self._token_overlap(query_tokens, self._query_tokens(content))
            if not exact_match and not compact_match and token_overlap < 0.34:
                continue
            idx = lower_content.find(query_lower)
            if idx < 0 and compact_query:
                normalized_idx = normalized_content.find(normalized_query)
                idx = normalized_idx if normalized_idx >= 0 else 0
            if idx < 0:
                idx = 0
            start = max(0, idx - 140)
            end = min(len(content), idx + 260)
            snippet = content[start:end].strip()
            results.append(
                RetrievedMemory(
                    artifact_id=f"file:{path.name}",
                    store="file",
                    score=self._score_path(path, exact_match=exact_match, compact_match=compact_match, token_overlap=token_overlap),
                    snippet=snippet,
                    reason=f"Matched file memory in {path.name}",
                    metadata={"path": str(path), "artifact_type": self._artifact_type_for_path(path)},
                )
            )
            if len(results) >= limit:
                break
        return results

    def _artifact_type_for_path(self, path: Path) -> str:
        if path == self.memory_file:
            return "fact"
        return "file_note"

    def _candidate_files(self) -> list[Path]:
        manual_notes = [
            path
            for path in sorted(self.memory_dir.rglob("*.md"))
            if path != self.memory_file
        ]
        candidates: list[Path] = [self.memory_file]
        candidates.extend(manual_notes[:24])
        return candidates

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").lower()).strip()

    @staticmethod
    def _compact_text(value: str) -> str:
        return "".join(ch for ch in (value or "").lower() if ch.isalnum())

    @staticmethod
    def _query_tokens(value: str) -> set[str]:
        return {token for token in re.split(r"\W+", (value or "").lower()) if len(token) >= 3}

    @staticmethod
    def _token_overlap(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / max(len(left), len(right))

    def _score_path(self, path: Path, *, exact_match: bool, compact_match: bool, token_overlap: float) -> float:
        base = 1.0 if path == self.memory_file else 0.82
        if exact_match:
            return min(1.0, base + 0.12)
        if compact_match:
            return min(0.96, base + 0.08)
        return min(0.92, base + token_overlap * 0.18)
