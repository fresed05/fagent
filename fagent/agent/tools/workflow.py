"""Workflow meta-tool for sequential tool execution with optional light LLM help."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from fagent.agent.tools.base import Tool
from fagent.agent.tools.registry import ToolRegistry
from fagent.prompts import PromptLoader
from fagent.providers.base import LLMProvider


class WorkflowTool(Tool):
    """Run sequential tool workflows with recovery and escalation support."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        provider: LLMProvider | None = None,
        *,
        model: str | None = None,
        max_tokens: int = 900,
        repair_callback: Callable[[str, str, str, str | None], None] | None = None,
    ):
        self.tool_registry = tool_registry
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self.prompts = PromptLoader.from_package()
        self.repair_callback = repair_callback
        self._session_key: str | None = None

    def set_context(self, session_key: str | None) -> None:
        """Attach the active session key for repair telemetry."""
        self._session_key = session_key

    @property
    def name(self) -> str:
        return "run_workflow"

    @property
    def description(self) -> str:
        return "Execute an ordered workflow of tool steps with optional light-LLM interpretation and recovery."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "minLength": 3},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "args": {"type": "object"},
                            "needs_llm": {"type": "boolean"},
                        },
                        "required": ["action"],
                    },
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "llm_assist_mode": {
                    "type": "string",
                    "enum": ["never", "on_error", "allow", "required"],
                },
                "escalation_policy": {
                    "type": "string",
                    "enum": ["return_control", "fail_fast"],
                },
            },
            "required": ["goal", "steps", "allowed_tools"],
        }

    async def execute(
        self,
        goal: str,
        steps: list[dict[str, Any] | str],
        allowed_tools: list[str],
        llm_assist_mode: str = "on_error",
        escalation_policy: str = "return_control",
    ) -> str:
        execution_log: list[dict[str, Any]] = []
        for index, raw_step in enumerate(steps, start=1):
            step = self._normalize_step(raw_step)
            handled = await self._execute_step(
                goal=goal,
                index=index,
                step=step,
                allowed_tools=allowed_tools,
                llm_assist_mode=llm_assist_mode,
                escalation_policy=escalation_policy,
                execution_log=execution_log,
                repair_budget=2,
            )
            if handled is not None:
                return handled
        return json.dumps(
            {"status": "completed", "goal": goal, "execution_log": execution_log},
            ensure_ascii=False,
            indent=2,
        )

    async def _execute_step(
        self,
        *,
        goal: str,
        index: int,
        step: dict[str, Any],
        allowed_tools: list[str],
        llm_assist_mode: str,
        escalation_policy: str,
        execution_log: list[dict[str, Any]],
        repair_budget: int,
    ) -> str | None:
        action = str(step.get("action", ""))
        args = step.get("args") or {}
        needs_llm = bool(step.get("needs_llm", False))

        if action not in allowed_tools:
            repaired = await self._repair_step(goal, execution_log, step, allowed_tools, "tool_not_allowed")
            if repaired is not None and repair_budget > 0 and repaired != step:
                if self.repair_callback:
                    self.repair_callback(
                        "workflow_repair",
                        f"tool_not_allowed:{action}",
                        json.dumps(repaired, ensure_ascii=False),
                        self._session_key,
                    )
                execution_log.append({"step": index, "repair_applied": repaired})
                return await self._execute_step(
                    goal=goal,
                    index=index,
                    step=repaired,
                    allowed_tools=allowed_tools,
                    llm_assist_mode=llm_assist_mode,
                    escalation_policy=escalation_policy,
                    execution_log=execution_log,
                    repair_budget=repair_budget - 1,
                )
            return json.dumps(
                {
                    "status": "blocked",
                    "goal": goal,
                    "failed_step": index,
                    "reason": f"Tool '{action}' is not in allowed_tools",
                    "normalized_step": step,
                    "execution_log": execution_log,
                },
                ensure_ascii=False,
                indent=2,
            )

        if needs_llm and llm_assist_mode in {"allow", "required"}:
            llm_note = await self._ask_light_llm(goal, execution_log, step)
            execution_log.append({"step": index, "action": action, "llm_note": llm_note})

        result = await self.tool_registry.execute(action, args)
        entry = {"step": index, "action": action, "args": args, "result": result}
        execution_log.append(entry)
        if isinstance(result, str) and result.startswith("Error"):
            repaired = await self._repair_step(goal, execution_log, step, allowed_tools, result)
            if repaired is not None and repair_budget > 0 and repaired != step:
                if self.repair_callback:
                    self.repair_callback(
                        "workflow_repair",
                        result[:240],
                        json.dumps(repaired, ensure_ascii=False),
                        self._session_key,
                    )
                entry["repair_retry"] = repaired
                return await self._execute_step(
                    goal=goal,
                    index=index,
                    step=repaired,
                    allowed_tools=allowed_tools,
                    llm_assist_mode=llm_assist_mode,
                    escalation_policy=escalation_policy,
                    execution_log=execution_log,
                    repair_budget=repair_budget - 1,
                )
            if llm_assist_mode in {"on_error", "allow", "required"}:
                recovery = await self._ask_light_llm(goal, execution_log, step)
                entry["recovery"] = recovery
            if escalation_policy == "fail_fast" or llm_assist_mode == "never":
                return json.dumps(
                    {
                        "status": "failed",
                        "goal": goal,
                        "failed_step": index,
                        "execution_log": execution_log,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            return json.dumps(
                {
                    "status": "escalate",
                    "goal": goal,
                    "failed_step": index,
                    "execution_log": execution_log,
                },
                ensure_ascii=False,
                indent=2,
            )
        return None

    def _normalize_step(self, step: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(step, str):
            action, args = self._parse_action_and_args(step)
            return {"action": action, "args": args, "needs_llm": False}

        normalized = dict(step)
        action_text = str(normalized.get("action", ""))
        args = normalized.get("args")
        if not isinstance(args, dict):
            args = {}
        if action_text and (" " in action_text or "=" in action_text or action_text.endswith(")")):
            parsed_action, parsed_args = self._parse_action_and_args(action_text)
            normalized["action"] = parsed_action
            normalized["args"] = {**parsed_args, **args}
        else:
            normalized["args"] = args
        return normalized

    def _parse_action_and_args(self, text: str) -> tuple[str, dict[str, Any]]:
        cleaned = text.strip()
        if cleaned.endswith(")") and "(" in cleaned:
            cleaned = cleaned[:-1].replace("(", " ", 1)
        tokens = re.findall(r'[^\s=]+="[^"]*"|[^\s=]+=\'[^\']*\'|"[^"]*"|\'[^\']*\'|\S+', cleaned)
        if not tokens:
            return "", {}
        action = tokens[0]
        raw_tokens = tokens[1:]
        args: dict[str, Any] = {}
        positional: list[str] = []
        for token in raw_tokens:
            item = token.strip().rstrip(",")
            if "=" in item:
                key, value = item.split("=", 1)
                args[key.strip()] = self._strip_wrapping_quotes(value.strip())
            else:
                positional.append(self._strip_wrapping_quotes(item))
        if positional:
            inferred = self._infer_positional_args(action, positional)
            args = {**inferred, **args}
        return action, args

    def _infer_positional_args(self, action: str, positional: list[str]) -> dict[str, Any]:
        tool = self.tool_registry.get(action)
        if tool is None:
            return {"value": positional[0]} if len(positional) == 1 else {"values": positional}
        params = tool.parameters or {}
        props = params.get("properties", {})
        required = [name for name in params.get("required", []) if name in props]
        ordered_keys = required + [name for name in props if name not in required]
        if not ordered_keys:
            return {"value": positional[0]} if len(positional) == 1 else {"values": positional}
        result: dict[str, Any] = {}
        for key, value in zip(ordered_keys, positional):
            result[key] = value
        return result

    def _strip_wrapping_quotes(self, value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]
        return value

    async def _ask_light_llm(
        self,
        goal: str,
        execution_log: list[dict[str, Any]],
        step: dict[str, Any],
    ) -> str:
        if self.provider is None or not self.model:
            return "No light LLM configured; returning control to the main agent."
        response = await self.provider.chat(
            messages=[
                {"role": "system", "content": self.prompts.load("system/workflow-tool.md").text},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "goal": goal,
                            "execution_log": execution_log,
                            "step": step,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0.1,
        )
        return (response.content or "").strip() or "Light LLM returned no guidance."

    async def _repair_step(
        self,
        goal: str,
        execution_log: list[dict[str, Any]],
        step: dict[str, Any],
        allowed_tools: list[str],
        error_text: str,
    ) -> dict[str, Any] | None:
        heuristics = self._heuristic_repair(step, allowed_tools)
        if heuristics is not None and heuristics != step:
            return heuristics
        if self.provider is None or not self.model:
            return None
        response = await self.provider.chat(
            messages=[
                {"role": "system", "content": self.prompts.load("system/workflow-tool.md").text},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "goal": goal,
                            "execution_log": execution_log,
                            "step": step,
                            "allowed_tools": allowed_tools,
                            "error": error_text,
                            "task": "Repair this workflow step and return one JSON object with action, args, needs_llm.",
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0.0,
        )
        repaired = self._extract_repaired_step(response.content or "")
        return self._normalize_step(repaired) if repaired else None

    def _heuristic_repair(self, step: dict[str, Any], allowed_tools: list[str]) -> dict[str, Any] | None:
        action = str(step.get("action", ""))
        args = dict(step.get("args") or {})
        if action in allowed_tools:
            return None
        for tool_name in allowed_tools:
            if action.startswith(tool_name):
                parsed_action, parsed_args = self._parse_action_and_args(action)
                if parsed_action == tool_name:
                    return {
                        "action": tool_name,
                        "args": {**parsed_args, **args},
                        "needs_llm": bool(step.get("needs_llm", False)),
                    }
        return None

    def _extract_repaired_step(self, content: str) -> dict[str, Any] | None:
        if not content.strip():
            return None
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
