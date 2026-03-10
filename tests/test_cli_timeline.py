from rich.console import Console

from fagent.cli.commands import _TurnTimeline


def test_timeline_aggregates_repeated_tool_events() -> None:
    console = Console(record=True, width=120)
    timeline = _TurnTimeline(console)
    timeline.start_turn()
    timeline.handle_event({
        "event": "tool",
        "tool_name": "memory_search",
        "arguments_preview": 'memory_search("latest")',
        "arguments_signature": '{"query":"latest"}',
        "status": "running",
    })
    timeline.handle_event({
        "event": "tool",
        "tool_name": "memory_search",
        "arguments_preview": 'memory_search("latest")',
        "arguments_signature": '{"query":"latest"}',
        "status": "ok",
    })
    timeline.handle_event({
        "event": "stage",
        "stage": "Draft ready",
        "status": "done",
        "content": "ready",
    })

    output = console.export_text()
    assert 'memory_search("latest") x2' in output

