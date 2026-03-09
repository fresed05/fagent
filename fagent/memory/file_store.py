"""Human-readable note storage for file memory."""

from __future__ import annotations

from pathlib import Path

from fagent.memory.policy import MemoryPolicy
from fagent.memory.types import EpisodeRecord, MemoryArtifact, RetrievedMemory
from fagent.utils.helpers import ensure_dir


class FileMemoryStore:
    """OpenClaw-style markdown memory files."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.daily_dir = ensure_dir(self.memory_dir / "daily")
        self.policy = MemoryPolicy()

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    def append_history(self, entry: str) -> None:
        with self.history_file.open("a", encoding="utf-8") as handle:
            handle.write(entry.rstrip() + "\n\n")

    def append_daily_note(self, episode: EpisodeRecord, summary: str) -> Path:
        day = episode.timestamp[:10]
        note_path = self.daily_dir / f"{day}.md"
        timestamp = episode.timestamp[:16].replace("T", " ")
        block = (
            f"## {timestamp} [{episode.turn_id}]\n"
            f"- Session: `{episode.session_key}`\n"
            f"- User: {episode.user_text.strip()}\n"
            f"- Assistant: {episode.assistant_text.strip()}\n"
            f"- Summary: {summary.strip()}\n\n"
        )
        with note_path.open("a", encoding="utf-8") as handle:
            handle.write(block)
        return note_path

    def ingest_episode(self, episode: EpisodeRecord, summary: str | None = None) -> list[MemoryArtifact]:
        summary = summary or self.policy.build_summary(episode)
        timestamp = episode.timestamp[:16].replace("T", " ")
        history_entry = f"[{timestamp}] {summary}"
        self.append_history(history_entry)
        daily_path = self.append_daily_note(episode, summary)

        artifacts = [
            MemoryArtifact(
                id=f"{episode.episode_id}:history",
                type="summary_note",
                content=history_entry,
                summary=summary,
                metadata={"session_key": episode.session_key, "turn_id": episode.turn_id},
                source_ref=str(self.history_file),
            ),
            MemoryArtifact(
                id=f"{episode.episode_id}:daily",
                type="daily_note",
                content=daily_path.read_text(encoding="utf-8"),
                summary=summary,
                metadata={"session_key": episode.session_key, "turn_id": episode.turn_id},
                source_ref=str(daily_path),
            ),
        ]

        if self.policy.should_update_long_term(episode):
            current = self.read_long_term().rstrip()
            addition = (
                f"\n## {episode.turn_id}\n"
                f"- Session: `{episode.session_key}`\n"
                f"- {summary.strip()}\n"
            )
            updated = (current + addition).strip() + "\n"
            self.write_long_term(updated)
            artifacts.append(
                MemoryArtifact(
                    id=f"{episode.episode_id}:memory",
                    type="fact",
                    content=updated,
                    summary=summary,
                    metadata={"session_key": episode.session_key, "turn_id": episode.turn_id},
                    source_ref=str(self.memory_file),
                )
            )

        return artifacts

    def retrieve(self, query: str, limit: int = 5) -> list[RetrievedMemory]:
        query_lower = query.lower()
        results: list[RetrievedMemory] = []
        candidates = [self.memory_file, self.history_file, *sorted(self.daily_dir.glob("*.md"), reverse=True)[:10]]
        for path in candidates:
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            if query_lower not in content.lower():
                continue
            idx = content.lower().find(query_lower)
            start = max(0, idx - 140)
            end = min(len(content), idx + 260)
            snippet = content[start:end].strip()
            results.append(
                RetrievedMemory(
                    artifact_id=f"file:{path.name}",
                    store="file",
                    score=1.0 if path == self.memory_file else 0.8,
                    snippet=snippet,
                    reason=f"Matched file memory in {path.name}",
                    metadata={"path": str(path)},
                )
            )
            if len(results) >= limit:
                break
        return results
