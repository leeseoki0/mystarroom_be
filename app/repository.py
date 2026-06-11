from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SAFETY_PREFERENCES = {
    "romance_minimized": False,
    "bright_tone": True,
    "short_replies": False,
    "night_rest_reminder": False,
}

DEFAULT_MEMORY_CONTROLS = {
    "long_term_memory_enabled": True,
    "allow_logbook_personalization": True,
}

DEFAULT_SUPPORT_STYLE = "따뜻한 응원형"


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
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    support_style TEXT NOT NULL,
                    safety_preferences TEXT NOT NULL,
                    memory_controls TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

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
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "profile_id" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN profile_id TEXT")

    def create_profile(
        self,
        support_style: str | None = None,
        safety_preferences: dict[str, Any] | None = None,
        memory_controls: dict[str, Any] | None = None,
        kind: str = "guest",
    ) -> dict[str, Any]:
        profile = {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "support_style": support_style or DEFAULT_SUPPORT_STYLE,
            "safety_preferences": merge_dict(DEFAULT_SAFETY_PREFERENCES, safety_preferences),
            "memory_controls": merge_dict(DEFAULT_MEMORY_CONTROLS, memory_controls),
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile["id"],
                    profile["kind"],
                    profile["support_style"],
                    json.dumps(profile["safety_preferences"], ensure_ascii=False),
                    json.dumps(profile["memory_controls"], ensure_ascii=False),
                    profile["created_at"],
                    profile["updated_at"],
                ),
            )
        return profile

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if row is None:
            return None
        return row_to_profile(row)

    def update_profile(
        self,
        profile_id: str,
        support_style: str | None = None,
        safety_preferences: dict[str, Any] | None = None,
        memory_controls: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        profile = self.get_profile(profile_id)
        if profile is None:
            return None
        if support_style is not None:
            profile["support_style"] = support_style
        profile["safety_preferences"] = merge_dict(profile["safety_preferences"], safety_preferences)
        profile["memory_controls"] = merge_dict(profile["memory_controls"], memory_controls)
        profile["updated_at"] = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE profiles
                SET support_style = ?, safety_preferences = ?, memory_controls = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    profile["support_style"],
                    json.dumps(profile["safety_preferences"], ensure_ascii=False),
                    json.dumps(profile["memory_controls"], ensure_ascii=False),
                    profile["updated_at"],
                    profile["id"],
                ),
            )
        return profile

    def create_session(self, plot_id: str, profile_id: str | None = None) -> dict[str, Any]:
        session = {
            "id": str(uuid.uuid4()),
            "profile_id": profile_id,
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
                INSERT INTO sessions (
                    id, profile_id, plot_id, step, total_steps, completed, trust, inspiration,
                    collaboration, support_balance, display_summary, safety_events, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["id"],
                    session["profile_id"],
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
                SET profile_id = ?, step = ?, completed = ?, trust = ?, inspiration = ?, collaboration = ?,
                    support_balance = ?, display_summary = ?, safety_events = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    session.get("profile_id"),
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

    def get_active_session_for_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM sessions
                WHERE profile_id = ? AND completed = 0
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (profile_id,),
            ).fetchone()
        if row is None:
            return None
        return row_to_session(row)

    def list_recent_logbook_entries_for_profile(self, profile_id: str, limit: int = 3) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT logbook_entries.*
                FROM logbook_entries
                INNER JOIN sessions ON sessions.id = logbook_entries.session_id
                WHERE sessions.profile_id = ?
                ORDER BY logbook_entries.created_at DESC
                LIMIT ?
                """,
                (profile_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]



def merge_dict(base: dict[str, Any], update: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base)
    if update:
        merged.update(update)
    return merged



def row_to_profile(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "support_style": row["support_style"],
        "safety_preferences": json.loads(row["safety_preferences"]),
        "memory_controls": json.loads(row["memory_controls"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }



def row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
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
