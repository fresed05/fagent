import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML

from fagent.cli import commands


@pytest.fixture
def mock_prompt_session():
    """Mock the global prompt session."""
    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock()
    with patch("fagent.cli.commands._PROMPT_SESSION", mock_session), \
         patch("fagent.cli.commands.patch_stdout"):
        yield mock_session


@pytest.mark.asyncio
async def test_read_interactive_input_async_returns_input(mock_prompt_session):
    """Test that _read_interactive_input_async returns the user input from prompt_session."""
    mock_prompt_session.prompt_async.return_value = "hello world"

    result = await commands._read_interactive_input_async()
    
    assert result == "hello world"
    mock_prompt_session.prompt_async.assert_called_once()
    args, _ = mock_prompt_session.prompt_async.call_args
    assert isinstance(args[0], HTML)  # Verify HTML prompt is used


@pytest.mark.asyncio
async def test_read_interactive_input_async_handles_eof(mock_prompt_session):
    """Test that EOFError converts to KeyboardInterrupt."""
    mock_prompt_session.prompt_async.side_effect = EOFError()

    with pytest.raises(KeyboardInterrupt):
        await commands._read_interactive_input_async()


def test_init_prompt_session_creates_session():
    """Test that _init_prompt_session initializes the global session."""
    # Ensure global is None before test
    commands._PROMPT_SESSION = None
    commands._PROMPT_CATALOG = ()
    
    with patch("fagent.cli.commands.PromptSession") as MockSession, \
         patch("fagent.cli.commands.FileHistory") as MockHistory, \
         patch("pathlib.Path.home") as mock_home:
        
        mock_home.return_value = MagicMock()
        
        commands._init_prompt_session()
        
        assert commands._PROMPT_SESSION is not None
        MockSession.assert_called_once()
        _, kwargs = MockSession.call_args
        assert kwargs["multiline"] is False
        assert kwargs["enable_open_in_editor"] is False
        assert kwargs["completer"] is not None
        assert kwargs["auto_suggest"] is not None
        assert kwargs["bottom_toolbar"] is not None


def test_hybrid_completer_suggests_slash_commands():
    completer = commands._HybridCommandCompleter(commands.CHAT_COMMANDS)

    items = list(completer.get_completions(Document("/he"), None))

    assert any(item.text == "/help" for item in items)


def test_hybrid_completer_suggests_nested_cli_commands():
    entries = (
        commands._CommandEntry(
            name="memory rebuild-vectors",
            description="Rebuild the vector index.",
            category="memory",
            example="fagent memory rebuild-vectors",
        ),
    )
    completer = commands._HybridCommandCompleter(entries)

    items = list(completer.get_completions(Document("memory reb"), None))

    assert any(item.text == "memory rebuild-vectors" for item in items)


def test_handle_interactive_command_help_prints_catalog(tmp_path):
    with patch("fagent.cli.commands._print_interactive_help") as mock_help:
        handled = commands._handle_interactive_command(
            "/help",
            session_id="cli:direct",
            workspace=tmp_path,
            model="test-model",
        )

    assert handled is True
    mock_help.assert_called_once()


def test_bottom_toolbar_shows_best_match():
    commands._PROMPT_CATALOG = (
        commands._CommandEntry(
            name="/status",
            description="Show the active interactive session state.",
            category="chat",
            example="/status",
        ),
    )
    session = MagicMock()
    session.default_buffer.document = Document("/st")
    with patch("fagent.cli.commands._PROMPT_SESSION", session):
        toolbar = commands._bottom_toolbar()

    assert "status" in toolbar.value
