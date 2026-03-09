"""Markdown prompt loader with fragment composition."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PromptTemplate:
    """Loaded prompt body with a stable content version."""

    path: str
    text: str
    version: str


class PromptLoader:
    """Load markdown prompts and inline reusable fragments."""

    _FRAGMENT_RE = re.compile(r"\{\{\s*fragment:([a-zA-Z0-9_./-]+)\s*\}\}")

    def __init__(self, root: Path):
        self.root = root

    @classmethod
    def from_workspace(cls, workspace: Path) -> "PromptLoader":
        return cls(workspace / "fagent" / "prompts")

    @classmethod
    def from_package(cls) -> "PromptLoader":
        return cls(Path(__file__).resolve().parent)

    def load(self, relative_path: str) -> PromptTemplate:
        resolved = (self.root / relative_path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Prompt file not found: {resolved}")
        raw = resolved.read_text(encoding="utf-8")
        text = self._compose(raw, stack=[resolved])
        version = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        return PromptTemplate(path=relative_path, text=text, version=version)

    def _compose(self, text: str, stack: list[Path]) -> str:
        def _replace(match: re.Match[str]) -> str:
            fragment_rel = match.group(1).strip()
            fragment_path = (self.root / fragment_rel).resolve()
            if fragment_path in stack:
                cycle = " -> ".join(str(item) for item in [*stack, fragment_path])
                raise ValueError(f"Prompt fragment cycle detected: {cycle}")
            if not fragment_path.exists():
                raise FileNotFoundError(f"Prompt fragment not found: {fragment_path}")
            fragment_text = fragment_path.read_text(encoding="utf-8")
            return self._compose(fragment_text, stack=[*stack, fragment_path])

        return self._FRAGMENT_RE.sub(_replace, text).strip()
