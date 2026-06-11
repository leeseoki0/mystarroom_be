from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    plot_id TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    total_steps INTEGER NOT NULL,
                    completed INTEGER NOT NULL,
                    trust INTEGER NOT NULL,
                    inspiration INTEGER NOT NULL,
                    collaboration INTEGER NOT NULL,
                    support_balance INTEGER NOT NULL,
                    display_summary TEXT NOT NULL,
                    safety_events TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS logbook_entries (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    reward_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                """
            )

    def create_session(self, plot_id: str) -> dict[str, Any]:
        session = {
            "id": str(uuid.uuid4()),
            "plot_id": plot_id,
            "step": 1,
            "total_steps": 3,
            "completed": False,
            "relationship": {
                "trust": 0,
                "inspiration": 0,
                "collaboration": 0,
                "support_balance": 0,
                "display_summary": "아직 첫 장면을 시작하지 않았어요.",
            },
            "safety_events": [],
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["id"],
                    session["plot_id"],
                    session["step"],
                    session["total_steps"],
                    int(session["completed"]),
                    session["relationship"]["trust"],
                    session["relationship"]["inspiration"],
                    session["relationship"]["collaboration"],
                    session["relationship"]["support_balance"],
                    session["relationship"]["display_summary"],
                    json.dumps(session["safety_events"], ensure_ascii=False),
                    session["created_at"],
                    session["updated_at"],
                ),
            )
        return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return row_to_session(row)

    def update_session(self, session: dict[str, Any]) -> None:
        session["updated_at"] = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET step = ?, completed = ?, trust = ?, inspiration = ?, collaboration = ?,
                    support_balance = ?, display_summary = ?, safety_events = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    session["step"],
                    int(session["completed"]),
                    session["relationship"]["trust"],
                    session["relationship"]["inspiration"],
                    session["relationship"]["collaboration"],
                    session["relationship"]["support_balance"],
                    session["relationship"]["display_summary"],
                    json.dumps(session["safety_events"], ensure_ascii=False),
                    session["updated_at"],
                    session["id"],
                ),
            )

    def add_logbook_entry(self, session_id: str, title: str, summary: str, reward_type: str) -> dict[str, Any]:
        entry = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "title": title,
            "summary": summary,
            "reward_type": reward_type,
            "created_at": utc_now(),
        }
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO logbook_entries VALUES (?, ?, ?, ?, ?, ?)",
                (entry["id"], session_id, title, summary, reward_type, entry["created_at"]),
            )
        return entry

    def list_logbook_entries(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM logbook_entries WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "plot_id": row["plot_id"],
        "step": row["step"],
        "total_steps": row["total_steps"],
        "completed": bool(row["completed"]),
        "relationship": {
            "trust": row["trust"],
            "inspiration": row["inspiration"],
            "collaboration": row["collaboration"],
            "support_balance": row["support_balance"],
            "display_summary": row["display_summary"],
        },
        "safety_events": json.loads(row["safety_events"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
