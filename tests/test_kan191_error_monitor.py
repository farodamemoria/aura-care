"""KAN-191: el monitor agrupa por fingerprint y no duplica tickets en Jira."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MONITOR_PATH = ROOT / "scripts" / "error_monitor.py"
spec = importlib.util.spec_from_file_location("faro_error_monitor", MONITOR_PATH)
monitor = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = monitor
spec.loader.exec_module(monitor)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    monitor.ensure_schema(conn)
    return conn


def _insert(conn, fingerprint: str, message: str = "fallo", created_at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO app_errors (id, app, version, message, context, traceback, created_at, fingerprint, ticket_key)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (
            f"id-{fingerprint}-{uuid4()}",
            "faro-movil",
            "0.1",
            message,
            "screen=inicio",
            "stack",
            created_at or datetime.now(timezone.utc).isoformat(),
            fingerprint,
        ),
    )
    conn.commit()


def test_same_fingerprint_creates_one_ticket_for_many_occurrences() -> None:
    conn = _db()
    _insert(conn, "aaaa1111bbbb2222")
    _insert(conn, "aaaa1111bbbb2222")
    created: list[tuple[str, int]] = []

    def create(first, occurrences):
        created.append((first["fingerprint"], occurrences))
        return "KAN-999"

    summary = monitor.process(conn, create, lambda key, body: None)
    assert summary == {"procesados": 2, "grupos": 1, "tickets": 1, "comentarios": 0}
    assert created == [("aaaa1111bbbb2222", 2)]
    keys = {row[0] for row in conn.execute("SELECT ticket_key FROM app_errors")}
    assert keys == {"KAN-999"}


def test_new_occurrence_after_ticket_comments_instead_of_duplicating() -> None:
    conn = _db()
    _insert(conn, "aaaa1111bbbb2222")
    monitor.process(conn, lambda first, n: "KAN-999", lambda key, body: None)
    _insert(conn, "aaaa1111bbbb2222")
    comments: list[str] = []

    def create(first, occurrences):
        raise AssertionError("no debe crear un segundo ticket")

    summary = monitor.process(conn, create, lambda key, body: comments.append(key))
    assert summary == {"procesados": 1, "grupos": 1, "tickets": 0, "comentarios": 1}
    assert comments == ["KAN-999"]
    rows = list(conn.execute("SELECT ticket_key FROM app_errors"))
    assert [row[0] for row in rows] == ["KAN-999", "KAN-999"]


def test_dry_run_does_not_touch_jira_or_assign() -> None:
    conn = _db()
    _insert(conn, "cccc3333dddd4444")
    calls: list[str] = []
    summary = monitor.process(
        conn,
        lambda first, n: calls.append("create") or "KAN-1",
        lambda key, body: calls.append("comment"),
        dry_run=True,
    )
    assert summary["tickets"] == 1
    assert calls == []
    assert conn.execute("SELECT ticket_key FROM app_errors").fetchone()[0] is None


def test_errors_outside_window_are_ignored() -> None:
    conn = _db()
    old = (datetime.now(timezone.utc).replace(year=2020)).isoformat()
    _insert(conn, "eeee5555ffff6666", created_at=old)
    summary = monitor.process(conn, lambda first, n: "KAN-2", lambda key, body: None, hours=24)
    assert summary["procesados"] == 0


def test_systemd_service_runs_the_deployed_repo_script() -> None:
    unit = (ROOT / "scripts" / "systemd" / "faro-error-monitor.service").read_text(encoding="utf-8")
    assert "/home/ec2-user/aura-backend/scripts/error_monitor.py" in unit
    assert " /home/ec2-user/error_monitor.py" not in unit
