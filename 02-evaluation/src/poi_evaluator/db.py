from __future__ import annotations

import json
import sqlite3
import sysconfig
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def migration_path() -> Path:
    module_path = Path(__file__).resolve()
    candidates = (
        module_path.parents[2] / "schema" / "001_initial.sql",
        module_path.parents[1] / "share" / "poi-evaluator" / "schema" / "001_initial.sql",
        Path(sysconfig.get_path("data")) / "share" / "poi-evaluator" / "schema" / "001_initial.sql",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Cannot locate the bundled schema/001_initial.sql migration")


def initialize(connection: sqlite3.Connection) -> None:
    sql = migration_path().read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", ("001_initial",)
    )
    connection.commit()


@contextmanager
def evaluation_run(
    connection: sqlite3.Connection, run_type: str, config: dict[str, Any]
) -> Iterator[int]:
    cursor = connection.execute(
        "INSERT INTO evaluation_runs(run_type, status, config_json) VALUES (?, 'running', ?)",
        (run_type, json.dumps(config, ensure_ascii=False, sort_keys=True)),
    )
    run_id = int(cursor.lastrowid)
    connection.commit()
    try:
        yield run_id
    except BaseException as exc:
        connection.execute(
            "UPDATE evaluation_runs SET status='failed', completed_at=CURRENT_TIMESTAMP, "
            "error_text=? WHERE id=?",
            (str(exc), run_id),
        )
        connection.commit()
        raise


def complete_run(
    connection: sqlite3.Connection, run_id: int, summary: dict[str, Any]
) -> None:
    connection.execute(
        "UPDATE evaluation_runs SET status='completed', completed_at=CURRENT_TIMESTAMP, "
        "summary_json=? WHERE id=?",
        (json.dumps(summary, ensure_ascii=False, sort_keys=True), run_id),
    )
    connection.commit()
