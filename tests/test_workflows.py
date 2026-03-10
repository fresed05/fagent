import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fagent.agent.tools.registry import ToolRegistry
from fagent.agent.tools.workflow import WorkflowTool
from fagent.cli.commands import app
from fagent.workflows import load_workflow_file


runner = CliRunner()


class _EchoTool:
    name = "echo"
    description = "Echo"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, **kwargs):
        return kwargs["text"]

    def to_schema(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}

    def cast_params(self, params):
        return params

    def validate_params(self, params):
        return []


def test_workflow_migrate_creates_json_and_deletes_prompt(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    prompt = legacy / "main.md"
    prompt.write_text("hello from workflow prompt", encoding="utf-8")

    result = runner.invoke(app, ["workflow", "migrate", str(legacy)])

    workflow_path = legacy / "workflow.json"
    assert result.exit_code == 0
    assert workflow_path.exists()
    assert not prompt.exists()

    payload = load_workflow_file(workflow_path)
    assert payload.workflow_id == "legacy"
    assert "main.md" in payload.prompts


@pytest.mark.asyncio
async def test_workflow_tool_loads_workflow_json(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(
        json.dumps(
            {
                "workflow_id": "echo-flow",
                "version": 1,
                "meta": {"name": "Echo Flow"},
                "prompts": {"guidance": {"text": "Use echo carefully"}},
                "defaults": {
                    "allowed_tools": ["echo"],
                    "llm_assist_mode": "allow",
                    "escalation_policy": "return_control",
                },
                "steps": [
                    {
                        "id": "step-1",
                        "action": "echo",
                        "args": {"text": "hello"},
                        "prompt_ref": "guidance",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = ToolRegistry()
    registry.register(_EchoTool())
    tool = WorkflowTool(registry, workspace=tmp_path, provider=None, model=None)

    payload = json.loads(await tool.execute(goal="echo", workflow_path=str(workflow_path)))

    assert payload["status"] == "completed"
    assert payload["workflow_path"] == str(workflow_path)
    assert payload["execution_log"][0]["prompt_ref"] == "guidance"
