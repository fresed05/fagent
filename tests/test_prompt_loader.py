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


def test_prompt_loader_reads_from_json_pack(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "prompts.json").write_text(
        """
        {
          "version": 1,
          "entries": {
            "fragments/shared.md": {"text": "shared fragment"},
            "system/example.md": {"text": "top\\n\\n{{fragment:fragments/shared.md}}"}
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    loader = PromptLoader(prompts_dir)

    template = loader.load("system/example.md")

    assert "shared fragment" in template.text
    assert template.path == "system/example.md"
