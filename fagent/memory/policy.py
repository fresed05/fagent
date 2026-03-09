"""Deterministic memory policy helpers."""

from __future__ import annotations

import re
from collections import Counter

from fagent.memory.types import EpisodeRecord

_WORD_RE = re.compile(r"[A-Za-zА-Яа-я0-9_/-]{3,}")
_STOPWORDS = {
    "this", "that", "with", "from", "have", "will", "were", "what", "when", "where",
    "which", "your", "about", "there", "their", "если", "для", "как", "что", "это",
    "или", "еще", "ещё", "надо", "нужно", "после", "before", "after", "into", "over",
    "then", "than", "just", "also", "very", "them", "they", "want", "agent", "memory",
}


class MemoryPolicy:
    """Rules deciding what should be kept and how it should be tagged."""

    def extract_topic_tags(self, text: str, limit: int = 8) -> list[str]:
        """Return stable-ish keywords for indexing and graph edges."""
        words = [
            match.group(0).lower()
            for match in _WORD_RE.finditer(text)
            if match.group(0).lower() not in _STOPWORDS
        ]
        counts = Counter(words)
        return [word for word, _ in counts.most_common(limit)]

    def should_update_long_term(self, episode: EpisodeRecord) -> bool:
        """Only persist durable memory when the turn likely contains a stable decision."""
        text = f"{episode.user_text}\n{episode.assistant_text}".lower()
        markers = (
            "we chose", "мы выбрали", "default", "по умолчанию", "use ", "используем",
            "stack", "архитектур", "решили", "будем", "decision", "предпочита",
        )
        return any(marker in text for marker in markers)

    def build_summary(self, episode: EpisodeRecord) -> str:
        """Create a short deterministic summary when LLM summarization is unavailable."""
        user = " ".join(episode.user_text.strip().split())
        assistant = " ".join(episode.assistant_text.strip().split())
        user = user[:220] + ("..." if len(user) > 220 else "")
        assistant = assistant[:220] + ("..." if len(assistant) > 220 else "")
        return f"User asked: {user}\nAssistant responded: {assistant}"
