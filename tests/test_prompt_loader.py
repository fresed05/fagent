from pathlib import Path

import pytest

from fagent.prompts.loader import PromptLoader


def test_prompt_loader_composes_fragments() -> None:
    loader = PromptLoader(Path(__file__).resolve().parents[1] / "fagent" / "prompts")

    template = loader.load("system/main-agent.md")

    assert "retrieved memory" in template.text.lower()
    assert template.version


def test_prompt_loader_raises_for_missing_file() -> None:
    loader = PromptLoader(Path(__file__).resolve().parents[1] / "fagent" / "prompts")

    with pytest.raises(FileNotFoundError):
        loader.load("system/missing.md")
