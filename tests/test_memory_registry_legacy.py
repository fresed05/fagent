import sqlite3
from pathlib import Path

from fagent.memory.orchestrator import MemoryOrchestrator
from fagent.memory.registry import MemoryRegistry
from fagent.memory.types import EpisodeRecord


def _create_legacy_registry(workspace: Path) -> Path:
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    db_path = memory_dir / "registry.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE artifacts (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE ingest_jobs (
                episode_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                retries INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE graph_jobs (
                job_id TEXT PRIMARY KEY,
                episode_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                prompt_version TEXT NOT NULL,
                model_role TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    return db_path


def test_legacy_registry_bootstrap_adds_columns_and_indexes(tmp_path: Path) -> None:
    db_path = _create_legacy_registry(tmp_path)

    MemoryRegistry(tmp_path)

    with sqlite3.connect(db_path) as conn:
        artifact_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()
        }
        graph_job_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(graph_jobs)").fetchall()
        }
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(artifacts)").fetchall()
        }

    assert {"session_key", "turn_id", "channel", "chat_id", "search_text"}.issubset(artifact_columns)
    assert "error" in graph_job_columns
    assert "idx_artifacts_type_created_at" in indexes
    assert "idx_artifacts_session_type_created_at" in indexes
    assert "idx_artifacts_session_created_at" in indexes


def test_legacy_registry_backfills_artifact_search_fields(tmp_path: Path) -> None:
    db_path = _create_legacy_registry(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO artifacts(id, type, content, summary, metadata_json, source_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-artifact",
                "session_turn",
                "Shadow context stores the compact brief",
                "Stored compact brief",
                '{"session_key":"cli:direct","turn_id":"turn-000001","channel":"cli","chat_id":"direct"}',
                "",
                "2026-03-10T10:00:00",
            ),
        )

    MemoryRegistry(tmp_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT session_key, turn_id, channel, chat_id, search_text
            FROM artifacts
            WHERE id = ?
            """,
            ("legacy-artifact",),
        ).fetchone()

    assert row is not None
    assert row[0] == "cli:direct"
    assert row[1] == "turn-000001"
    assert row[2] == "cli"
    assert row[3] == "direct"
    assert "shadow context" in row[4]
    assert "cli:direct" in row[4]


def test_memory_orchestrator_bootstraps_legacy_registry_and_queries_it(tmp_path: Path) -> None:
    db_path = _create_legacy_registry(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO artifacts(id, type, content, summary, metadata_json, source_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-session-turn",
                "session_turn",
                "Vector recall failed because the provider mismatched embeddings",
                "Embedding provider mismatch",
                '{"session_key":"cli:direct","turn_id":"turn-000002","channel":"cli","chat_id":"direct"}',
                "",
                "2026-03-10T10:01:00",
            ),
        )

    orchestrator = MemoryOrchestrator(workspace=tmp_path, provider=None, model="test-model")

    results = orchestrator.registry.search_artifacts("provider mismatch", session_key="cli:direct", limit=10)
    assert any(item.id == "legacy-session-turn" for item in results)

    episode = EpisodeRecord(
        episode_id="ep-new",
        session_key="cli:direct",
        turn_id="turn-000003",
        channel="cli",
        chat_id="direct",
        user_text="please remember repaired registry bootstrap",
        assistant_text="registry bootstrap works on legacy sqlite now",
        timestamp="2026-03-10T10:02:00",
    )

    import asyncio

    asyncio.run(orchestrator.ingest_episode(episode))
    artifacts = orchestrator.registry.list_session_artifacts("cli:direct", artifact_type="session_turn", limit=20)
    assert any(item.id == "ep-new" for item in artifacts)
