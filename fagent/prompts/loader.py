"""Prompt loader with JSON-pack support and fragment composition."""

from __future__ import annotations

import hashlib
import json
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
    """Load prompts from a JSON bundle or fallback markdown files."""

    _FRAGMENT_RE = re.compile(r"\{\{\s*fragment:([a-zA-Z0-9_./-]+)\s*\}\}")
    _PACK_FILENAME = "prompts.json"

    def __init__(self, root: Path):
        self.root = root
        self._pack_cache: dict[str, str] | None = None

    @classmethod
    def from_workspace(cls, workspace: Path) -> "PromptLoader":
        return cls(workspace / "fagent" / "prompts")

    @classmethod
    def from_package(cls) -> "PromptLoader":
        return cls(Path(__file__).resolve().parent)

    def load(self, relative_path: str) -> PromptTemplate:
        raw = self._read_entry(relative_path)
        text = self._compose(raw, stack=[relative_path])
        version = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        return PromptTemplate(path=relative_path, text=text, version=version)

    def _load_pack(self) -> dict[str, str]:
        if self._pack_cache is not None:
            return self._pack_cache

        pack_path = self.root / self._PACK_FILENAME
        if not pack_path.exists():
            self._pack_cache = {}
            return self._pack_cache

        data = json.loads(pack_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Prompt pack must be a JSON object: {pack_path}")

        entries = data.get("entries", data)
        if not isinstance(entries, dict):
            raise ValueError(f"Prompt pack entries must be a JSON object: {pack_path}")

        normalized: dict[str, str] = {}
        for key, value in entries.items():
            if isinstance(value, dict):
                text = value.get("text")
            else:
                text = value
            if not isinstance(key, str) or not isinstance(text, str):
                raise ValueError(f"Invalid prompt pack entry for key {key!r}: expected string text")
            normalized[key] = text

        self._pack_cache = normalized
        return normalized

    def _read_entry(self, relative_path: str) -> str:
        entries = self._load_pack()
        if relative_path in entries:
            return entries[relative_path]

        resolved = (self.root / relative_path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Prompt file not found: {resolved}")
        return resolved.read_text(encoding="utf-8")

    def _compose(self, text: str, stack: list[str]) -> str:
        def _replace(match: re.Match[str]) -> str:
            fragment_rel = match.group(1).strip()
            if fragment_rel in stack:
                cycle = " -> ".join([*stack, fragment_rel])
                raise ValueError(f"Prompt fragment cycle detected: {cycle}")
            fragment_text = self._read_entry(fragment_rel)
            return self._compose(fragment_text, stack=[*stack, fragment_rel])

        return self._FRAGMENT_RE.sub(_replace, text).strip()
