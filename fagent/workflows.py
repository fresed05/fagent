"""Workflow JSON schema, loading, and legacy prompt migration helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_DEFAULTS = {
    "allowed_tools": [],
    "llm_assist_mode": "on_error",
    "escalation_policy": "return_control",
}


@dataclass(slots=True)
class WorkflowDefinition:
    """Validated workflow definition loaded from workflow.json."""

    workflow_id: str
    version: int
    meta: dict[str, Any]
    prompts: dict[str, dict[str, str]]
    defaults: dict[str, Any]
    steps: list[dict[str, Any]]
    path: Path


def validate_workflow_payload(payload: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """Validate and normalize a workflow payload."""
    if not isinstance(payload, dict):
        raise ValueError(f"Workflow payload must be an object: {path or '<memory>'}")

    workflow_id = payload.get("workflow_id")
    if not isinstance(workflow_id, str) or len(workflow_id.strip()) < 1:
        raise ValueError("workflow_id must be a non-empty string")

    version = payload.get("version")
    if version != 1:
        raise ValueError("workflow version must be 1")

    meta = payload.get("meta") or {}
    if not isinstance(meta, dict):
        raise ValueError("meta must be an object")
    if "name" in meta and not isinstance(meta["name"], str):
        raise ValueError("meta.name must be a string when provided")
    if "description" in meta and not isinstance(meta["description"], str):
        raise ValueError("meta.description must be a string when provided")

    prompts = payload.get("prompts") or {}
    if not isinstance(prompts, dict):
        raise ValueError("prompts must be an object")
    normalized_prompts: dict[str, dict[str, str]] = {}
    for key, value in prompts.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("prompt keys must be non-empty strings")
        if not isinstance(value, dict) or not isinstance(value.get("text"), str):
            raise ValueError(f"prompt '{key}' must be an object with string field 'text'")
        normalized_prompts[key] = {"text": value["text"]}

    defaults = {**_DEFAULTS, **(payload.get("defaults") or {})}
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be an object")
    allowed_tools = defaults.get("allowed_tools")
    if not isinstance(allowed_tools, list) or not all(isinstance(item, str) for item in allowed_tools):
        raise ValueError("defaults.allowed_tools must be an array of strings")
    if defaults.get("llm_assist_mode") not in {"never", "on_error", "allow", "required"}:
        raise ValueError("defaults.llm_assist_mode is invalid")
    if defaults.get("escalation_policy") not in {"return_control", "fail_fast"}:
        raise ValueError("defaults.escalation_policy is invalid")

    steps = payload.get("steps") or []
    if not isinstance(steps, list):
        raise ValueError("steps must be an array")
    normalized_steps: list[dict[str, Any]] = []
    for idx, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, dict):
            raise ValueError(f"step {idx} must be an object")
        step_id = raw_step.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError(f"step {idx} requires non-empty id")
        action = raw_step.get("action")
        prompt_ref = raw_step.get("prompt_ref")
        if action is not None and not isinstance(action, str):
            raise ValueError(f"step {step_id}: action must be a string")
        if prompt_ref is not None and not isinstance(prompt_ref, str):
            raise ValueError(f"step {step_id}: prompt_ref must be a string")
        if prompt_ref and prompt_ref not in normalized_prompts:
            raise ValueError(f"step {step_id}: unknown prompt_ref '{prompt_ref}'")
        args = raw_step.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError(f"step {step_id}: args must be an object")
        needs_llm = raw_step.get("needs_llm", False)
        if not isinstance(needs_llm, bool):
            raise ValueError(f"step {step_id}: needs_llm must be a boolean")
        on_error = raw_step.get("on_error")
        if on_error is not None and not isinstance(on_error, dict):
            raise ValueError(f"step {step_id}: on_error must be an object")
        normalized_steps.append(
            {
                "id": step_id,
                "action": action,
                "args": args,
                "needs_llm": needs_llm,
                "prompt_ref": prompt_ref,
                "on_error": on_error,
            }
        )

    return {
        "workflow_id": workflow_id.strip(),
        "version": 1,
        "meta": meta,
        "prompts": normalized_prompts,
        "defaults": defaults,
        "steps": normalized_steps,
    }


def load_workflow_file(path: Path) -> WorkflowDefinition:
    """Load and validate one workflow.json file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized = validate_workflow_payload(payload, path=path)
    return WorkflowDefinition(path=path, **normalized)


def resolve_workflow_path(workspace: Path, workflow_path: str | None = None, workflow_ref: str | None = None) -> Path:
    """Resolve workflow path from an explicit path or workspace-local ref."""
    if workflow_path:
        resolved = Path(workflow_path).expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Workflow file not found: {resolved}")
        return resolved
    if workflow_ref:
        candidate = (workspace / "workflows" / workflow_ref / "workflow.json").resolve()
        if candidate.exists():
            return candidate
        flat = (workspace / "workflows" / f"{workflow_ref}.json").resolve()
        if flat.exists():
            return flat
        raise FileNotFoundError(f"Workflow ref not found in workspace: {workflow_ref}")
    raise ValueError("workflow_path or workflow_ref is required")


def migrate_legacy_workflow_path(target: Path) -> tuple[Path, list[Path]]:
    """Convert a legacy prompt file or directory to workflow.json and return deleted markdown files."""
    target = target.expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"Legacy workflow path not found: {target}")

    if target.is_file():
        if target.suffix.lower() != ".md":
            raise ValueError("Only legacy markdown prompt files can be migrated")
        prompt_files = [target]
        base_dir = target.parent
        workflow_id = target.stem
    else:
        prompt_files = sorted(
            item for item in target.rglob("*.md")
            if item.is_file() and item.name.lower() not in {"readme.md", "skill.md", "agents.md", "tools.md", "user.md", "soul.md", "heartbeat.md"}
        )
        if not prompt_files:
            raise ValueError("No legacy workflow prompt markdown files found")
        base_dir = target
        workflow_id = target.name

    prompts: dict[str, dict[str, str]] = {}
    for item in prompt_files:
        rel = item.relative_to(base_dir).as_posix()
        prompts[rel] = {"text": item.read_text(encoding="utf-8")}

    payload = validate_workflow_payload(
        {
            "workflow_id": workflow_id,
            "version": 1,
            "meta": {"name": workflow_id},
            "prompts": prompts,
            "defaults": dict(_DEFAULTS),
            "steps": [],
        },
        path=base_dir / "workflow.json",
    )
    workflow_path = base_dir / "workflow.json"
    workflow_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    deleted: list[Path] = []
    for item in prompt_files:
        item.unlink()
        deleted.append(item)
    return workflow_path, deleted
