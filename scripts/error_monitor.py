"""KAN-191: monitor de errores de los aplicativos -> tickets de Jira.

Lee la tabla `app_errors` del backend de Faro, agrupa los errores nuevos por
fingerprint y crea un unico ticket por fallo (o comenta las ocurrencias nuevas
en el ticket ya abierto). Pensado para ejecutarse desde systemd cada 15 minutos.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone

DB = os.environ.get("AURA_EVENT_DB", "/home/ec2-user/aura-backend/faro-events.db")
TOKEN = os.environ.get("AURA_JIRA_API_TOKEN", "")
EMAIL = os.environ.get("AURA_JIRA_EMAIL", "farodamemoria@gmail.com")
BASE = os.environ.get("AURA_JIRA_BASE", "https://farodamemoria.atlassian.net")
PROJECT = os.environ.get("AURA_JIRA_PROJECT", "KAN")
ISSUE_TYPE_ID = os.environ.get("AURA_JIRA_ERROR_ISSUE_TYPE", "10003")
LABELS = ["opencode", "error-auto"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def jira_request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    auth = "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def adf_paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def issue_description(first: sqlite3.Row, occurrences: int) -> dict:
    text = (
        f"Aplicacion: {first['app']} {first['version']}\n"
        f"Error: {first['message']}\n"
        f"Primera vez: {first['created_at']} (ocurrencias en la ventana: {occurrences})\n"
        f"Contexto: {(first['context'] or '')[:1500]}\n\n"
        f"Traza:\n{(first['traceback'] or '')[:3000]}\n\n"
        "Generado automaticamente por el monitor de errores (KAN-191). "
        "Firmado por: opencode."
    )
    return {"type": "doc", "version": 1, "content": [adf_paragraph(text)]}


def comment_text(first: sqlite3.Row, occurrences: int) -> dict:
    text = (
        f"Nuevas ocurrencias del mismo fallo: {occurrences}\n"
        f"Ultima vez: {first['created_at']}\n"
        f"App: {first['app']} {first['version']}\n"
        "Monitor de errores KAN-191."
    )
    return {"type": "doc", "version": 1, "content": [adf_paragraph(text)]}


def pending_rows(conn: sqlite3.Connection, hours: int) -> list[sqlite3.Row]:
    since = (utc_now() - timedelta(hours=hours)).isoformat()
    return list(
        conn.execute(
            "SELECT * FROM app_errors WHERE ticket_key IS NULL AND created_at >= ? "
            "ORDER BY created_at ASC",
            (since,),
        )
    )


def group_by_fingerprint(rows: list[sqlite3.Row]) -> dict[str, list[sqlite3.Row]]:
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["fingerprint"], []).append(row)
    return grouped


def existing_ticket(conn: sqlite3.Connection, fingerprint: str) -> str | None:
    row = conn.execute(
        "SELECT ticket_key FROM app_errors WHERE fingerprint = ? AND ticket_key IS NOT NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (fingerprint,),
    ).fetchone()
    return row["ticket_key"] if row else None


def mark_assigned(conn: sqlite3.Connection, fingerprint: str, key: str) -> None:
    conn.execute(
        "UPDATE app_errors SET ticket_key = ? WHERE fingerprint = ? AND ticket_key IS NULL",
        (key, fingerprint),
    )
    conn.commit()


def process(
    conn: sqlite3.Connection,
    create_ticket,
    add_comment,
    hours: int = 24,
    dry_run: bool = False,
) -> dict[str, int]:
    rows = pending_rows(conn, hours)
    grouped = group_by_fingerprint(rows)
    created = 0
    commented = 0
    for fingerprint, items in grouped.items():
        first = items[0]
        occurrences = len(items)
        key = existing_ticket(conn, fingerprint)
        if key:
            if not dry_run:
                add_comment(key, comment_text(first, occurrences))
                mark_assigned(conn, fingerprint, key)
            commented += 1
            print("comentario", key, "para", first["app"], fingerprint, "x", occurrences)
            continue
        if dry_run:
            created += 1
            print("crearia ticket para", first["app"], fingerprint, "x", occurrences)
            continue
        key = create_ticket(first, occurrences)
        mark_assigned(conn, fingerprint, key)
        created += 1
        print("ticket", key, "para", first["app"], fingerprint, "x", occurrences)
    summary = {
        "procesados": len(rows),
        "grupos": len(grouped),
        "tickets": created,
        "comentarios": commented,
    }
    print(" ".join(f"{name} {value}" for name, value in summary.items()))
    return summary


def jira_create_ticket(first: sqlite3.Row, occurrences: int) -> str:
    issue = jira_request(
        "POST",
        "/rest/api/3/issue",
        {
            "fields": {
                "project": {"key": PROJECT},
                "summary": f"[Auto] Error en {first['app']}: {first['message'][:110]}",
                "description": issue_description(first, occurrences),
                "issuetype": {"id": ISSUE_TYPE_ID},
                "labels": LABELS,
            }
        },
    )
    key = issue.get("key")
    if not key:
        raise RuntimeError("Jira no devolvio la clave del ticket")
    return key


def jira_add_comment(key: str, body: dict) -> None:
    jira_request("POST", f"/rest/api/3/issue/{key}/comment", {"body": body})


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS app_errors (
            id TEXT PRIMARY KEY, app TEXT NOT NULL, version TEXT NOT NULL,
            message TEXT NOT NULL, context TEXT NOT NULL, traceback TEXT NOT NULL,
            created_at TEXT NOT NULL, fingerprint TEXT NOT NULL, ticket_key TEXT
        )"""
    )
    conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor de errores de Faro (KAN-191)")
    parser.add_argument("--db", default=DB, help="ruta de faro-events.db")
    parser.add_argument("--hours", type=int, default=24, help="ventana de errores en horas")
    parser.add_argument("--dry-run", action="store_true", help="no escribe en Jira")
    args = parser.parse_args()
    if not args.dry_run and not TOKEN:
        print("sin AURA_JIRA_API_TOKEN")
        return 2
    conn = sqlite3.connect(args.db)
    ensure_schema(conn)
    process(conn, jira_create_ticket, jira_add_comment, args.hours, args.dry_run)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
