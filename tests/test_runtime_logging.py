from pathlib import Path

from loguru import logger

from fagent.runtime_logging import setup_runtime_logging


def test_setup_runtime_logging_creates_log_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fagent.runtime_logging.get_logs_dir", lambda: tmp_path)

    log_path = setup_runtime_logging(verbose=False)
    logger.bind(session_key="cli:direct", turn_id="turn-1", stage="Pre-search", status="ok").info("turn_stage")
    logger.complete()

    assert log_path.exists()
    assert "turn_stage" in log_path.read_text(encoding="utf-8")

