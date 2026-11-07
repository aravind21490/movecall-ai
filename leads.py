"""Lead storage (SQLite). One row per finished call."""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone

FIELDS = [
    "name",
    "callback_number",
    "pickup",
    "destination",
    "move_date",
    "size",
    "access",
    "services",
    "special_items",
    "callback_time",
]
REQUIRED = ["name", "callback_number", "pickup", "destination"]
MAX_LEN = 300

_lock = threading.Lock()


def _db_path() -> str:
    return os.getenv("MOVECALL_DB", "movecall.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    cols = ", ".join(f"{f} TEXT" for f in FIELDS)
    with _lock, _connect() as conn:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS leads ("
            f"id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, "
            f"created_at TEXT NOT NULL, {cols})"
        )


def _clean(value) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:MAX_LEN] or None


def save_lead(data: dict) -> dict:
    """Store a lead. Missing required fields make it 'partial', never an error."""
    init_db()
    row = {f: _clean(data.get(f)) for f in FIELDS}
    status = "new" if all(row[f] for f in REQUIRED) else "partial"
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock, _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO leads (status, created_at, {', '.join(FIELDS)}) "
            f"VALUES (?, ?, {', '.join('?' for _ in FIELDS)})",
            [status, created, *[row[f] for f in FIELDS]],
        )
        lead_id = cur.lastrowid
    return {"id": lead_id, "status": status, "created_at": created, **row}


def get_lead(lead_id: int) -> dict | None:
    init_db()
    with _lock, _connect() as conn:
        r = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(r) if r else None


def list_leads() -> list[dict]:
    init_db()
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def set_status(lead_id: int, status: str) -> bool:
    init_db()
    with _lock, _connect() as conn:
        cur = conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
        return cur.rowcount == 1
