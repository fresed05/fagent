import asyncio
import json
import time
from pathlib import Path

import pytest

from fagent.agent.loop import AgentLoop
from fagent.agent.tools.moa import MoaTool
from fagent.bus.queue import MessageBus
from fagent.config.schema import Config, MoaToolConfig
from fagent.providers.base import LLMProvider, LLMResponse


class _StubProvider(LLMProvider):
    def __init__(self, response_text: str, delay: float = 0.0):
        super().__init__(api_key="test")
        self.response_text = response_text
        self.delay = delay

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ):
        if self.delay:
            await asyncio.sleep(self.delay)
        return LLMResponse(content=self.response_text, usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})

    def get_default_model(self) -> str:
        return "stub"


class _MapFactory:
    def __init__(self, providers):
        self.providers = providers

    def build_for_profile(self, profile_name: str, fallback_model: str | None = None):
        provider = self.providers[profile_name]
        profile = type(
            "Profile",
            (),
            {
                "model": profile_name,
                "provider_kind": "stub",
                "max_tokens": 256,
                "temperature": 0.1,
            },
        )()
        return provider, profile

    def build_from_profile(self, profile):
        return self.providers[profile.model]


@pytest.mark.asyncio
async def test_moa_tool_happy_path_returns_selected_answer() -> None:
    tool = MoaTool(
        provider_factory=_MapFactory(
            {
                "worker_a": _StubProvider("candidate from A"),
                "worker_b": _StubProvider("candidate from B"),
                "judge": _StubProvider(
                    '{"winner":"worker_b","judge_summary":"B is more complete","selected_answer":"final answer from judge"}'
                ),
            }
        ),
        config=MoaToolConfig.model_validate(
            {
                "presets": {
                    "default": {
                        "workerModels": ["worker_a", "worker_b"],
                        "judgeModel": "judge",
                        "returnCandidates": True,
                    }
                }
            }
        ),
    )

    payload = json.loads(await tool.execute(prompt="Solve it"))

    assert payload["status"] == "completed"
    assert payload["winner"] == "worker_b"
    assert payload["selected_answer"] == "final answer from judge"
    assert len(payload["candidates"]) == 2


@pytest.mark.asyncio
async def test_moa_tool_partial_worker_failure_still_uses_judge() -> None:
    class _FailProvider(_StubProvider):
        async def chat(self, *args, **kwargs):
            raise RuntimeError("worker failed")

    tool = MoaTool(
        provider_factory=_MapFactory(
            {
                "worker_a": _FailProvider(""),
                "worker_b": _StubProvider("candidate from B"),
                "judge": _StubProvider(
                    '{"winner":"worker_b","judge_summary":"Only B succeeded","selected_answer":"judge final"}'
                ),
            }
        ),
        config=MoaToolConfig.model_validate(
            {"presets": {"default": {"workerModels": ["worker_a", "worker_b"], "judgeModel": "judge"}}}
        ),
    )

    payload = json.loads(await tool.execute(prompt="Solve it"))

    assert payload["status"] == "completed"
    assert payload["winner"] == "worker_b"
    assert len(payload["failures"]) == 1


@pytest.mark.asyncio
async def test_moa_tool_judge_failure_falls_back_to_first_success() -> None:
    tool = MoaTool(
        provider_factory=_MapFactory(
            {
                "worker_a": _StubProvider("candidate from A"),
                "worker_b": _StubProvider("candidate from B"),
                "judge": _StubProvider("not valid json"),
            }
        ),
        config=MoaToolConfig.model_validate(
            {"presets": {"default": {"workerModels": ["worker_a", "worker_b"], "judgeModel": "judge"}}}
        ),
    )

    payload = json.loads(await tool.execute(prompt="Solve it"))

    assert payload["status"] == "partial"
    assert payload["winner"] == "worker_a"
    assert payload["selected_answer"] == "candidate from A"


@pytest.mark.asyncio
async def test_moa_tool_runs_workers_concurrently() -> None:
    tool = MoaTool(
        provider_factory=_MapFactory(
            {
                "worker_a": _StubProvider("candidate from A", delay=0.2),
                "worker_b": _StubProvider("candidate from B", delay=0.2),
                "judge": _StubProvider(
                    '{"winner":"worker_a","judge_summary":"done","selected_answer":"final"}'
                ),
            }
        ),
        config=MoaToolConfig.model_validate(
            {"presets": {"default": {"workerModels": ["worker_a", "worker_b"], "judgeModel": "judge", "parallelism": 2}}}
        ),
    )

    started = time.perf_counter()
    await tool.execute(prompt="Solve it")
    elapsed = time.perf_counter() - started

    assert elapsed < 0.35


class _LoopProvider(LLMProvider):
    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ):
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "stub"


def test_agent_loop_registers_moa_tool(tmp_path: Path) -> None:
    config = Config.model_validate(
        {
            "providers": {"main_provider": {"providerKind": "custom", "apiKey": "test", "apiBase": "http://localhost:8000/v1"}},
            "agents": {"defaults": {"provider": "main_provider", "model": "gpt-5.4"}},
        }
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_LoopProvider(api_key="test"),
        workspace=tmp_path,
        app_config=config,
        memory_config=config.memory,
    )

    assert loop.tools.has("moa")
