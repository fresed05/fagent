from fagent.agent.context import ContextBuilder
from fagent.agent.loop import AgentLoop
from fagent.session.manager import Session


def _mk_loop() -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop._TOOL_RESULT_MAX_CHARS = 500
    return loop


def test_save_turn_skips_multimodal_user_when_only_runtime_context() -> None:
    loop = _mk_loop()
    session = Session(key="test:runtime-only")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{"role": "user", "content": [{"type": "text", "text": runtime}]}],
        skip=0,
    )
    assert session.messages == []


def test_save_turn_keeps_image_placeholder_after_runtime_strip() -> None:
    loop = _mk_loop()
    session = Session(key="test:image")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image]"}]


def test_save_turn_assigns_incrementing_turn_ids() -> None:
    loop = _mk_loop()
    session = Session(key="test:turns")

    turn_id, _ = loop._save_turn(
        session,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
        skip=0,
    )

    assert turn_id == "turn-000001"
    assert session.metadata["turn_seq"] == 1
    assert all(msg["turn_id"] == "turn-000001" for msg in session.messages)
