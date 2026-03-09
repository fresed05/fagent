"""Mixture-of-agents tool for multi-model synthesis."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import json_repair

from fagent.agent.tools.base import Tool
from fagent.config.schema import MoaToolConfig
from fagent.providers.base import LLMResponse
from fagent.providers.factory import ProviderFactory


class MoaTool(Tool):
    """Fan a request out to worker models and judge the results."""

    def __init__(self, provider_factory: ProviderFactory, config: MoaToolConfig):
        self.provider_factory = provider_factory
        self.config = config

    @property
    def name(self) -> str:
        return "moa"

    @property
    def description(self) -> str:
        return "Query multiple configured models in parallel and synthesize the best answer with a judge model."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "minLength": 3},
                "preset": {"type": "string"},
                "system_prompt": {"type": "string"},
                "evaluation_criteria": {"type": "string"},
                "max_candidates": {"type": "integer", "minimum": 1},
            },
            "required": ["prompt"],
        }

    async def execute(
        self,
        prompt: str,
        preset: str = "default",
        system_prompt: str | None = None,
        evaluation_criteria: str | None = None,
        max_candidates: int | None = None,
    ) -> str:
        if not self.config.enabled:
            return json.dumps({"status": "disabled", "message": "MOA tool is disabled."}, ensure_ascii=False)

        preset_name = preset or self.config.default_preset
        preset_cfg = self.config.presets.get(preset_name)
        if preset_cfg is None:
            return json.dumps(
                {"status": "error", "message": f"Unknown MOA preset '{preset_name}'."},
                ensure_ascii=False,
            )

        worker_names = list(preset_cfg.worker_models)
        if max_candidates is not None:
            worker_names = worker_names[:max_candidates]
        if not worker_names:
            return json.dumps(
                {"status": "error", "message": f"Preset '{preset_name}' has no worker models."},
                ensure_ascii=False,
            )

        semaphore = asyncio.Semaphore(max(1, preset_cfg.parallelism))
        worker_results = await asyncio.gather(
            *(self._run_worker(semaphore, worker_name, prompt, system_prompt, preset_cfg) for worker_name in worker_names)
        )

        successful = [item for item in worker_results if item["status"] == "ok"]
        failed = [item for item in worker_results if item["status"] != "ok"]
        usage = self._sum_usage(item.get("usage", {}) for item in worker_results)

        if not successful:
            return json.dumps(
                {
                    "status": "failed",
                    "message": "All MOA worker models failed.",
                    "failures": failed,
                    "usage": usage,
                },
                ensure_ascii=False,
                indent=2,
            )

        judge_result = await self._run_judge(
            preset_cfg.judge_model,
            prompt=prompt,
            system_prompt=system_prompt,
            evaluation_criteria=evaluation_criteria,
            candidates=successful,
            preset_name=preset_name,
            preset_cfg=preset_cfg,
        )
        usage = self._sum_usage([usage, judge_result.get("usage", {})])

        if judge_result["status"] != "ok":
            fallback = successful[0]
            payload = {
                "status": "partial",
                "selected_answer": fallback["answer"],
                "judge_summary": judge_result.get("error", "Judge failed; used first successful candidate."),
                "winner": fallback["model_profile"],
                "candidates": successful if preset_cfg.return_candidates else [],
                "failures": failed,
                "usage": usage,
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)

        payload = {
            "status": "completed",
            "selected_answer": judge_result["selected_answer"],
            "judge_summary": judge_result["judge_summary"],
            "winner": judge_result["winner"],
            "usage": usage,
            "failures": failed,
        }
        if preset_cfg.return_candidates:
            payload["candidates"] = successful
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def _run_worker(
        self,
        semaphore: asyncio.Semaphore,
        worker_name: str,
        prompt: str,
        system_prompt: str | None,
        preset_cfg,
    ) -> dict[str, Any]:
        async with semaphore:
            try:
                provider, profile = self.provider_factory.build_for_profile(worker_name)
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                response = await provider.chat(
                    messages=messages,
                    model=profile.model,
                    max_tokens=preset_cfg.worker_max_tokens or profile.max_tokens,
                    temperature=(
                        preset_cfg.temperature_override
                        if preset_cfg.temperature_override is not None
                        else profile.temperature
                    ),
                )
                answer = (response.content or "").strip()
                if not answer:
                    raise ValueError("Worker returned empty content.")
                return {
                    "status": "ok",
                    "model_profile": worker_name,
                    "provider_kind": profile.provider_kind,
                    "model": profile.model,
                    "answer": answer,
                    "reasoning": response.reasoning_content if preset_cfg.include_reasoning else None,
                    "usage": response.usage,
                }
            except Exception as exc:
                return {
                    "status": "error",
                    "model_profile": worker_name,
                    "error": str(exc),
                    "usage": {},
                }

    async def _run_judge(
        self,
        judge_name: str,
        *,
        prompt: str,
        system_prompt: str | None,
        evaluation_criteria: str | None,
        candidates: list[dict[str, Any]],
        preset_name: str,
        preset_cfg,
    ) -> dict[str, Any]:
        try:
            provider, profile = self.provider_factory.build_for_profile(judge_name)
            candidate_lines = []
            for item in candidates:
                record = {
                    "model_profile": item["model_profile"],
                    "provider_kind": item["provider_kind"],
                    "model": item["model"],
                    "answer": item["answer"],
                }
                if preset_cfg.include_reasoning and item.get("reasoning"):
                    record["reasoning"] = item["reasoning"]
                candidate_lines.append(record)

            judge_system = (
                "You are the MOA judge. Pick the best candidate, synthesize the final answer, and return JSON "
                'with keys: winner, judge_summary, selected_answer.'
            )
            if system_prompt:
                judge_system = f"{system_prompt}\n\n{judge_system}"
            judge_user = {
                "preset": preset_name,
                "prompt": prompt,
                "evaluation_criteria": evaluation_criteria or "Prefer the most correct, complete, and actionable answer.",
                "candidates": candidate_lines,
            }
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": judge_system},
                    {"role": "user", "content": json.dumps(judge_user, ensure_ascii=False)},
                ],
                model=profile.model,
                max_tokens=preset_cfg.judge_max_tokens or profile.max_tokens,
                temperature=(
                    preset_cfg.temperature_override
                    if preset_cfg.temperature_override is not None
                    else profile.temperature
                ),
            )
            return self._parse_judge_response(response)
        except Exception as exc:
            return {"status": "error", "error": str(exc), "usage": {}}

    def _parse_judge_response(self, response: LLMResponse) -> dict[str, Any]:
        try:
            raw = json_repair.loads((response.content or "").strip())
            winner = str(raw.get("winner", "")).strip()
            selected_answer = str(raw.get("selected_answer", "")).strip()
            judge_summary = str(raw.get("judge_summary", "")).strip()
            if not winner or not selected_answer:
                raise ValueError("Judge response did not include winner and selected_answer.")
            return {
                "status": "ok",
                "winner": winner,
                "selected_answer": selected_answer,
                "judge_summary": judge_summary or "Judge selected the strongest candidate and synthesized the answer.",
                "usage": response.usage,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc), "usage": response.usage}

    def _sum_usage(self, usage_values) -> dict[str, int]:
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for usage in usage_values:
            for key in totals:
                totals[key] += int((usage or {}).get(key, 0))
        return totals
