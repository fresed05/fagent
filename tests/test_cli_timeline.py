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


def test_timeline_shows_background_pending_summary_before_post_turn_finishes() -> None:
    console = Console(record=True, width=120)
    timeline = _TurnTimeline(console)
    timeline.start_turn()

    timeline.handle_event({
        "event": "stage",
        "stage": "Turn complete",
        "status": "done",
        "content": "Turn complete",
    })

    output = console.export_text()
    assert "Graph: pending (background)" in output
    assert "Vector: pending (background)" in output
    assert "Summary: pending (background)" in output


def test_timeline_shows_graph_failure_reason_after_turn_complete() -> None:
    console = Console(record=True, width=120)
    timeline = _TurnTimeline(console)
    timeline.start_turn()

    timeline.handle_event({
        "event": "stage",
        "stage": "Turn complete",
        "status": "done",
        "content": "Turn complete",
    })
    timeline.handle_event({
        "event": "stage",
        "stage": "Building graph",
        "status": "skipped",
        "content": "skipped: graph_extract_unavailable",
        "extra": {},
        "error": "",
    })

    output = console.export_text()
    assert "Graph: pending (background)" in output
    assert "Building graph skipped: graph_extract_unavailable" in output
