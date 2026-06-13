from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .plot_cards import COMMON_SAFETY, PLOT_CARDS

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
DEFAULT_PLOT_STATUS = "draft"
DEFAULT_PLOT_APPROVAL_STATUS = "pending"
DEFAULT_TEMPLATE_STATUS = "draft"
DEFAULT_TEMPLATE_APPROVAL_STATUS = "pending"

DEFAULT_SAFETY_TEMPLATES = [
    {
        "id": "fictional-ip-boundary",
        "name": "가상 IP 경계 응답",
        "category": "fictional_ip_boundary",
        "template": "실제 인물/IP 요청은 거절하고, 동일 감정을 가상 세계관 설정으로 안전하게 전환한다.",
        "guidance": "실제 인물 또는 외부 IP를 직접 재현하지 않고, 서비스 내부의 허구 설정과 안전한 감정 표현으로만 응답한다.",
    },
    {
        "id": "dependency-rest-prompt",
        "name": "과몰입 휴식 권유",
        "category": "dependency_risk",
        "template": "정서적 의존 표현이 감지되면 답변 강도를 낮추고 잠깐 쉬어갈 수 있는 제안을 먼저 제공한다.",
        "guidance": "과몰입을 강화하지 말고 휴식, 호흡, 주변 지원 자원 같은 안전한 대안 행동으로 전환한다.",
    },
    {
        "id": "privacy-guardrail",
        "name": "개인정보/외부연락 차단",
        "category": "privacy_contact",
        "template": "연락처 교환이나 외부 이동 요청은 차단하고 서비스 내부의 안전한 대안 행동만 제시한다.",
        "guidance": "개인정보 수집, 외부 메신저 이동, 오프라인 접촉 제안 없이 플랫폼 안의 안전한 상호작용만 안내한다.",
    },
]


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
                    user_deletable INTEGER NOT NULL DEFAULT 1,
                    deleted_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS plot_cards (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    member_role TEXT NOT NULL,
                    one_line_hook TEXT NOT NULL,
                    relationship_frame TEXT NOT NULL,
                    estimated_time TEXT NOT NULL,
                    quest_type TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    opening_scene TEXT NOT NULL,
                    choices TEXT NOT NULL,
                    completion_reward TEXT NOT NULL,
                    safety TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approval_status TEXT NOT NULL,
                    disabled_at TEXT,
                    source TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS safety_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    template TEXT NOT NULL,
                    guidance TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approval_status TEXT NOT NULL,
                    disabled_at TEXT,
                    source TEXT NOT NULL,
                    validation TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    profile_id TEXT,
                    category TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id),
                    FOREIGN KEY(profile_id) REFERENCES profiles(id)
                );

                CREATE TABLE IF NOT EXISTS content_reports (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT,
                    session_id TEXT,
                    logbook_entry_id TEXT,
                    category TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    details TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id),
                    FOREIGN KEY(session_id) REFERENCES sessions(id),
                    FOREIGN KEY(logbook_entry_id) REFERENCES logbook_entries(id)
                );

                CREATE TABLE IF NOT EXISTS llm_settings (
                    id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    base_url TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    model TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "profile_id" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN profile_id TEXT")

            logbook_columns = {row["name"] for row in conn.execute("PRAGMA table_info(logbook_entries)").fetchall()}
            if "user_deletable" not in logbook_columns:
                conn.execute("ALTER TABLE logbook_entries ADD COLUMN user_deletable INTEGER NOT NULL DEFAULT 1")
            if "deleted_at" not in logbook_columns:
                conn.execute("ALTER TABLE logbook_entries ADD COLUMN deleted_at TEXT")

            self.seed_plot_cards(conn)
            self.seed_safety_templates(conn)

    def seed_plot_cards(self, conn: sqlite3.Connection) -> None:
        for index, card in enumerate(PLOT_CARDS, start=1):
            now = utc_now()
            conn.execute(
                """
                INSERT OR IGNORE INTO plot_cards (
                    id, title, member_id, member_role, one_line_hook, relationship_frame,
                    estimated_time, quest_type, tags, opening_scene, choices,
                    completion_reward, safety, status, approval_status, disabled_at,
                    source, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card["id"],
                    card["title"],
                    card["member_id"],
                    card["member_role"],
                    card["one_line_hook"],
                    card["relationship_frame"],
                    card["estimated_time"],
                    card["quest_type"],
                    json.dumps(card["tags"], ensure_ascii=False),
                    card["opening_scene"],
                    json.dumps(card["choices"], ensure_ascii=False),
                    json.dumps(card["completion_reward"], ensure_ascii=False),
                    json.dumps(card.get("safety", COMMON_SAFETY), ensure_ascii=False),
                    "published",
                    "approved",
                    None,
                    "seed",
                    index,
                    now,
                    now,
                ),
            )

    def seed_safety_templates(self, conn: sqlite3.Connection) -> None:
        for template in DEFAULT_SAFETY_TEMPLATES:
            now = utc_now()
            conn.execute(
                """
                INSERT OR IGNORE INTO safety_templates (
                    id, name, category, template, guidance, status, approval_status,
                    disabled_at, source, validation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template["id"],
                    template["name"],
                    template["category"],
                    template["template"],
                    template["guidance"],
                    "published",
                    "approved",
                    None,
                    "seed",
                    json.dumps({"ok": True, "errors": [], "blocked_categories": []}, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def get_llm_settings(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM llm_settings WHERE id = 'default'").fetchone()
        if row is None:
            return None
        return {
            "enabled": bool(row["enabled"]),
            "base_url": row["base_url"],
            "api_key": row["api_key"],
            "model": row["model"],
            "updated_at": row["updated_at"],
        }

    def update_llm_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_llm_settings() or {
            "enabled": False,
            "base_url": "",
            "api_key": "",
            "model": "",
            "updated_at": utc_now(),
        }
        if "enabled" in payload and payload["enabled"] is not None:
            current["enabled"] = bool(payload["enabled"])
        for key in ("base_url", "model"):
            if key in payload and payload[key] is not None:
                current[key] = str(payload[key]).strip()
        if "api_key" in payload and payload["api_key"] is not None:
            api_key = str(payload["api_key"]).strip()
            if api_key:
                current["api_key"] = api_key
        current["updated_at"] = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_settings (id, enabled, base_url, api_key, model, updated_at)
                VALUES ('default', ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    enabled = excluded.enabled,
                    base_url = excluded.base_url,
                    api_key = excluded.api_key,
                    model = excluded.model,
                    updated_at = excluded.updated_at
                """,
                (
                    1 if current["enabled"] else 0,
                    current["base_url"],
                    current["api_key"],
                    current["model"],
                    current["updated_at"],
                ),
            )
        return current

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
                "INSERT INTO profiles VALUES (?, ?, ?, ?, ?, ?, ?)",
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

    def list_plot_cards(self, include_disabled: bool = False, admin: bool = False) -> list[dict[str, Any]]:
        where_clauses: list[str] = []
        if not include_disabled:
            where_clauses.append("disabled_at IS NULL")
        if not admin:
            where_clauses.append("status = 'published'")
            where_clauses.append("approval_status = 'approved'")
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM plot_cards
                {where_sql}
                ORDER BY sort_order ASC, created_at ASC
                """
            ).fetchall()
        return [row_to_plot_card(row) for row in rows]

    def get_plot_card(self, plot_id: str, include_disabled: bool = False, admin: bool = False) -> dict[str, Any] | None:
        cards = self.list_plot_cards(include_disabled=include_disabled, admin=admin)
        return next((card for card in cards if card["id"] == plot_id), None)

    def create_plot_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        plot_id = str(payload["id"])
        card = normalize_plot_card_payload(payload)
        card["id"] = plot_id
        card["created_at"] = now
        card["updated_at"] = now
        card["disabled_at"] = None
        card["source"] = str(payload.get("source") or "admin")
        card["sort_order"] = int(payload.get("sort_order") or self.next_plot_sort_order())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO plot_cards (
                    id, title, member_id, member_role, one_line_hook, relationship_frame,
                    estimated_time, quest_type, tags, opening_scene, choices,
                    completion_reward, safety, status, approval_status, disabled_at,
                    source, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                plot_card_insert_tuple(card),
            )
        created = self.get_plot_card(plot_id, include_disabled=True, admin=True)
        assert created is not None
        return created

    def update_plot_card(self, plot_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_plot_card(plot_id, include_disabled=True, admin=True)
        if current is None:
            return None
        merged = merge_plot_card(current, payload)
        merged["updated_at"] = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE plot_cards
                SET title = ?, member_id = ?, member_role = ?, one_line_hook = ?,
                    relationship_frame = ?, estimated_time = ?, quest_type = ?,
                    tags = ?, opening_scene = ?, choices = ?, completion_reward = ?,
                    safety = ?, status = ?, approval_status = ?, disabled_at = ?,
                    source = ?, sort_order = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    merged["title"],
                    merged["member_id"],
                    merged["member_role"],
                    merged["one_line_hook"],
                    merged["relationship_frame"],
                    merged["estimated_time"],
                    merged["quest_type"],
                    json.dumps(merged["tags"], ensure_ascii=False),
                    merged["opening_scene"],
                    json.dumps(merged["choices"], ensure_ascii=False),
                    json.dumps(merged["completion_reward"], ensure_ascii=False),
                    json.dumps(merged["safety"], ensure_ascii=False),
                    merged["status"],
                    merged["approval_status"],
                    merged["disabled_at"],
                    merged["source"],
                    merged["sort_order"],
                    merged["updated_at"],
                    plot_id,
                ),
            )
        return self.get_plot_card(plot_id, include_disabled=True, admin=True)

    def disable_plot_card(self, plot_id: str) -> dict[str, Any] | None:
        current = self.get_plot_card(plot_id, include_disabled=True, admin=True)
        if current is None:
            return None
        if current["disabled_at"] is None:
            current["disabled_at"] = utc_now()
        return self.update_plot_card(plot_id, current)

    def next_plot_sort_order(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS sort_order FROM plot_cards").fetchone()
        return int(row["sort_order"]) + 1

    def list_safety_templates(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        where_sql = ""
        if not include_disabled:
            where_sql = "WHERE disabled_at IS NULL"
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM safety_templates
                {where_sql}
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [row_to_safety_template(row) for row in rows]

    def get_safety_template(self, template_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM safety_templates WHERE id = ?", (template_id,)).fetchone()
        if row is None:
            return None
        return row_to_safety_template(row)

    def create_safety_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        template = normalize_safety_template_payload(payload)
        template["id"] = str(payload.get("id") or f"st_{uuid.uuid4().hex[:10]}")
        template["created_at"] = now
        template["updated_at"] = now
        template["disabled_at"] = None
        template["source"] = str(payload.get("source") or "admin")
        template["validation"] = dict(payload.get("validation") or {"ok": True, "errors": [], "blocked_categories": []})
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO safety_templates (
                    id, name, category, template, guidance, status, approval_status,
                    disabled_at, source, validation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template["id"],
                    template["name"],
                    template["category"],
                    template["template"],
                    template["guidance"],
                    template["status"],
                    template["approval_status"],
                    template["disabled_at"],
                    template["source"],
                    json.dumps(template["validation"], ensure_ascii=False),
                    template["created_at"],
                    template["updated_at"],
                ),
            )
        created = self.get_safety_template(template["id"])
        assert created is not None
        return created

    def update_safety_template(self, template_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_safety_template(template_id)
        if current is None:
            return None
        merged = merge_safety_template(current, payload)
        merged["updated_at"] = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE safety_templates
                SET name = ?, category = ?, template = ?, guidance = ?, status = ?,
                    approval_status = ?, disabled_at = ?, source = ?, validation = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    merged["name"],
                    merged["category"],
                    merged["template"],
                    merged["guidance"],
                    merged["status"],
                    merged["approval_status"],
                    merged["disabled_at"],
                    merged["source"],
                    json.dumps(merged["validation"], ensure_ascii=False),
                    merged["updated_at"],
                    template_id,
                ),
            )
        return self.get_safety_template(template_id)

    def disable_safety_template(self, template_id: str) -> dict[str, Any] | None:
        current = self.get_safety_template(template_id)
        if current is None:
            return None
        if current["disabled_at"] is None:
            current["disabled_at"] = utc_now()
        return self.update_safety_template(template_id, current)

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

    def reset_session(self, session_id: str) -> dict[str, Any] | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        deleted_at = utc_now()
        with self.connect() as conn:
            deleted_logbook_entries = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM logbook_entries
                WHERE session_id = ? AND deleted_at IS NULL
                """,
                (session_id,),
            ).fetchone()["count"]
            conn.execute(
                """
                UPDATE logbook_entries
                SET deleted_at = COALESCE(deleted_at, ?)
                WHERE session_id = ?
                """,
                (deleted_at, session_id),
            )
        session["completed"] = True
        session["step"] = 1
        session["relationship"] = {
            "trust": 0,
            "inspiration": 0,
            "collaboration": 0,
            "support_balance": 0,
            "display_summary": "리셋되어 새 장면을 시작할 수 있어요.",
        }
        cleared_safety_events = len(session["safety_events"])
        session["safety_events"] = []
        self.update_session(session)
        return {
            "session": session,
            "cleared": {
                "logbook_entries": int(deleted_logbook_entries),
                "safety_events": cleared_safety_events,
            },
        }

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
            "user_deletable": True,
            "deleted_at": None,
            "created_at": utc_now(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO logbook_entries (
                    id, session_id, title, summary, reward_type, user_deletable, deleted_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["id"],
                    session_id,
                    entry["title"],
                    entry["summary"],
                    entry["reward_type"],
                    int(entry["user_deletable"]),
                    entry["deleted_at"],
                    entry["created_at"],
                ),
            )
        return entry

    def list_logbook_entries(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM logbook_entries
                WHERE session_id = ? AND deleted_at IS NULL
                ORDER BY created_at DESC
                """,
                (session_id,),
            ).fetchall()
        return [row_to_logbook_entry(row) for row in rows]

    def delete_logbook_entry(self, session_id: str, entry_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM logbook_entries WHERE id = ? AND session_id = ?",
                (entry_id, session_id),
            ).fetchone()
            if row is None:
                return None
            if not bool(row["user_deletable"]):
                return "forbidden"
            if row["deleted_at"] is not None:
                return "already_deleted"
            conn.execute(
                "UPDATE logbook_entries SET deleted_at = ? WHERE id = ? AND session_id = ?",
                (utc_now(), entry_id, session_id),
            )
        return "deleted"

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
                WHERE sessions.profile_id = ? AND logbook_entries.deleted_at IS NULL
                ORDER BY logbook_entries.created_at DESC
                LIMIT ?
                """,
                (profile_id, limit),
            ).fetchall()
        return [row_to_logbook_entry(row) for row in rows]

    def list_recent_memory_summaries_for_session(self, session_id: str, limit: int = 3) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT summary
                FROM logbook_entries
                WHERE session_id = ? AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [str(row["summary"]) for row in rows]

    def add_chat_message(self, session_id: str, role: str, content: str) -> dict[str, Any]:
        message = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": utc_now(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message["id"], session_id, role, content, message["created_at"]),
            )
        return message

    def list_chat_messages(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, created_at
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [row_to_chat_message(row) for row in reversed(rows)]

    def get_logbook_entry(self, entry_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM logbook_entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            return None
        return row_to_logbook_entry(row)

    def reset_profile_state(self, profile_id: str) -> int:
        now = utc_now()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM sessions WHERE profile_id = ? AND completed = 0",
                (profile_id,),
            ).fetchall()
            conn.execute(
                """
                UPDATE sessions
                SET completed = 1, updated_at = ?
                WHERE profile_id = ? AND completed = 0
                """,
                (now, profile_id),
            )
        return len(rows)

    def create_content_report(
        self,
        *,
        profile_id: str | None,
        session_id: str | None,
        logbook_entry_id: str | None,
        category: str,
        reason: str,
        details: str = "",
    ) -> dict[str, Any]:
        report = {
            "id": f"rpt_{uuid.uuid4().hex[:12]}",
            "profile_id": profile_id,
            "session_id": session_id,
            "logbook_entry_id": logbook_entry_id,
            "category": category,
            "reason": reason,
            "details": details,
            "status": "received",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO content_reports (
                    id, profile_id, session_id, logbook_entry_id, category, reason, details, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report["id"],
                    report["profile_id"],
                    report["session_id"],
                    report["logbook_entry_id"],
                    report["category"],
                    report["reason"],
                    report["details"],
                    report["status"],
                    report["created_at"],
                    report["updated_at"],
                ),
            )
        return report

    def list_content_reports(self, status: str | None = None) -> list[dict[str, Any]]:
        where_sql = ""
        params: tuple[Any, ...] = ()
        if status is not None:
            where_sql = "WHERE status = ?"
            params = (status,)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM content_reports
                {where_sql}
                ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
        return [row_to_content_report(row) for row in rows]


def merge_dict(base: dict[str, Any], update: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base)
    if update:
        merged.update(update)
    return merged


def normalize_plot_card_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(payload["title"]),
        "member_id": str(payload["member_id"]),
        "member_role": str(payload["member_role"]),
        "one_line_hook": str(payload["one_line_hook"]),
        "relationship_frame": str(payload["relationship_frame"]),
        "estimated_time": str(payload["estimated_time"]),
        "quest_type": str(payload["quest_type"]),
        "tags": list(payload["tags"]),
        "opening_scene": str(payload["opening_scene"]),
        "choices": list(payload["choices"]),
        "completion_reward": dict(payload["completion_reward"]),
        "safety": merge_dict(COMMON_SAFETY, payload.get("safety")),
        "status": str(payload.get("status") or DEFAULT_PLOT_STATUS),
        "approval_status": str(payload.get("approval_status") or DEFAULT_PLOT_APPROVAL_STATUS),
    }


def merge_plot_card(current: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for field in [
        "title",
        "member_id",
        "member_role",
        "one_line_hook",
        "relationship_frame",
        "estimated_time",
        "quest_type",
        "opening_scene",
        "status",
        "approval_status",
        "source",
        "disabled_at",
        "sort_order",
    ]:
        if field in payload and payload[field] is not None:
            merged[field] = payload[field]
    if "tags" in payload and payload["tags"] is not None:
        merged["tags"] = list(payload["tags"])
    if "choices" in payload and payload["choices"] is not None:
        merged["choices"] = list(payload["choices"])
    if "completion_reward" in payload and payload["completion_reward"] is not None:
        merged["completion_reward"] = dict(payload["completion_reward"])
    if "safety" in payload and payload["safety"] is not None:
        merged["safety"] = merge_dict(merged["safety"], payload["safety"])
    return merged


def plot_card_insert_tuple(card: dict[str, Any]) -> tuple[Any, ...]:
    return (
        card["id"],
        card["title"],
        card["member_id"],
        card["member_role"],
        card["one_line_hook"],
        card["relationship_frame"],
        card["estimated_time"],
        card["quest_type"],
        json.dumps(card["tags"], ensure_ascii=False),
        card["opening_scene"],
        json.dumps(card["choices"], ensure_ascii=False),
        json.dumps(card["completion_reward"], ensure_ascii=False),
        json.dumps(card["safety"], ensure_ascii=False),
        card["status"],
        card["approval_status"],
        card["disabled_at"],
        card["source"],
        card["sort_order"],
        card["created_at"],
        card["updated_at"],
    )


def normalize_safety_template_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(payload["name"]),
        "category": str(payload["category"]),
        "template": str(payload["template"]),
        "guidance": str(payload.get("guidance") or ""),
        "status": str(payload.get("status") or DEFAULT_TEMPLATE_STATUS),
        "approval_status": str(payload.get("approval_status") or DEFAULT_TEMPLATE_APPROVAL_STATUS),
    }


def merge_safety_template(current: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for field in [
        "name",
        "category",
        "template",
        "guidance",
        "status",
        "approval_status",
        "disabled_at",
        "source",
    ]:
        if field in payload and payload[field] is not None:
            merged[field] = payload[field]
    if "validation" in payload and payload["validation"] is not None:
        merged["validation"] = dict(payload["validation"])
    return merged


def slugify_identifier(prefix: str, value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    normalized = normalized.strip("_") or uuid.uuid4().hex[:8]
    return f"{prefix}{normalized}"


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


def row_to_logbook_entry(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "title": row["title"],
        "summary": row["summary"],
        "reward_type": row["reward_type"],
        "user_deletable": bool(row["user_deletable"]),
        "deleted_at": row["deleted_at"],
        "created_at": row["created_at"],
    }


def row_to_chat_message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "created_at": row["created_at"],
    }


def row_to_plot_card(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "member_id": row["member_id"],
        "member_role": row["member_role"],
        "one_line_hook": row["one_line_hook"],
        "relationship_frame": row["relationship_frame"],
        "estimated_time": row["estimated_time"],
        "quest_type": row["quest_type"],
        "tags": json.loads(row["tags"]),
        "opening_scene": row["opening_scene"],
        "choices": json.loads(row["choices"]),
        "completion_reward": json.loads(row["completion_reward"]),
        "safety": json.loads(row["safety"]),
        "status": row["status"],
        "approval_status": row["approval_status"],
        "disabled": row["disabled_at"] is not None,
        "disabled_at": row["disabled_at"],
        "source": row["source"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_safety_template(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "template": row["template"],
        "guidance": row["guidance"],
        "status": row["status"],
        "approval_status": row["approval_status"],
        "disabled": row["disabled_at"] is not None,
        "disabled_at": row["disabled_at"],
        "source": row["source"],
        "validation": json.loads(row["validation"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_content_report(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "session_id": row["session_id"],
        "logbook_entry_id": row["logbook_entry_id"],
        "category": row["category"],
        "reason": row["reason"],
        "details": row["details"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_report(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "profile_id": row["profile_id"],
        "category": row["category"],
        "detail": row["detail"],
        "source": row["source"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
