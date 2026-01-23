from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


class Storage:
    """Lightweight SQLite helper for conversations and leads."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._initialize()

    def _initialize(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    routing TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations (id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT,
                    name TEXT,
                    email TEXT,
                    phone TEXT,
                    contact_method TEXT,
                    preferred_time TEXT,
                    intent TEXT,
                    urgency TEXT,
                    summary TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_profiles (
                    conversation_id TEXT PRIMARY KEY,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    stage TEXT,
                    intent TEXT,
                    urgency TEXT,
                    contact_name TEXT,
                    product_type TEXT,
                    product_sku TEXT,
                    product_name TEXT,
                    inventory_status TEXT,
                    style TEXT,
                    metal TEXT,
                    stone TEXT,
                    shape TEXT,
                    budget TEXT,
                    ring_size TEXT,
                    consult_type TEXT,
                    requested_date TEXT,
                    contact_email TEXT,
                    contact_phone TEXT,
                    summary TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations (id)
                )
                """
            )
        self._ensure_lead_columns()
        self._ensure_profile_columns()

    def _ensure_lead_columns(self) -> None:
        columns = {
            "contact_method": "TEXT",
            "preferred_time": "TEXT",
            "urgency": "TEXT",
            "profile_json": "TEXT",
        }
        cursor = self._conn.execute("PRAGMA table_info(leads)")
        existing = {row[1] for row in cursor.fetchall()}
        with self._conn:
            for column, col_type in columns.items():
                if column not in existing:
                    self._conn.execute(
                        f"ALTER TABLE leads ADD COLUMN {column} {col_type}"
                    )

    def _ensure_profile_columns(self) -> None:
        columns = {
            "stage": "TEXT",
            "contact_name": "TEXT",
            "product_sku": "TEXT",
            "product_name": "TEXT",
            "inventory_status": "TEXT",
        }
        cursor = self._conn.execute("PRAGMA table_info(conversation_profiles)")
        existing = {row[1] for row in cursor.fetchall()}
        with self._conn:
            for column, col_type in columns.items():
                if column not in existing:
                    self._conn.execute(
                        f"ALTER TABLE conversation_profiles ADD COLUMN {column} {col_type}"
                    )

    def ensure_conversation(self, conversation_id: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO conversations (id) VALUES (?)",
                    (conversation_id,),
                )

    def log_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        routing: Optional[Dict[str, Any]] = None,
    ) -> None:
        routing_json = json.dumps(routing or {})
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, routing)
                    VALUES (?, ?, ?, ?)
                    """,
                    (conversation_id, role, content, routing_json),
                )

    def get_messages(self, conversation_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(
            """
            SELECT role, content FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        rows = cursor.fetchall()
        return [
            {"role": row["role"], "content": row["content"]}
            for row in reversed(rows)
        ]

    def count_assistant_messages(self, conversation_id: str) -> int:
        cursor = self._conn.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE conversation_id = ? AND role = 'assistant'
            """,
            (conversation_id,),
        )
        (count,) = cursor.fetchone()
        return int(count)

    def save_lead(
        self,
        conversation_id: str,
        name: str,
        email: str,
        phone: str,
        contact_method: str,
        preferred_time: str,
        intent: str,
        urgency: str,
        summary: str,
        profile_snapshot: Dict[str, Any],
    ) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO leads (
                        conversation_id,
                        name,
                        email,
                        phone,
                        contact_method,
                        preferred_time,
                        intent,
                        urgency,
                        summary,
                        profile_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        name,
                        email,
                        phone,
                        contact_method,
                        preferred_time,
                        intent,
                        urgency,
                        summary,
                        json.dumps(profile_snapshot or {}),
                    ),
                )

    def lead_exists(self, conversation_id: str, email: str, phone: str) -> bool:
        cursor = self._conn.execute(
            """
            SELECT COUNT(*) FROM leads
            WHERE conversation_id = ?
              AND (
                (email != '' AND email = ?)
                OR (phone != '' AND phone = ?)
              )
            """,
            (conversation_id, email, phone),
        )
        (count,) = cursor.fetchone()
        return int(count) > 0

    def list_leads(self) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(
            """
            SELECT id, conversation_id, name, email, phone, contact_method, preferred_time,
                   intent, urgency, summary, profile_json, created_at
            FROM leads
            ORDER BY id DESC
            LIMIT 200
            """
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_profile(self, conversation_id: str) -> Dict[str, Any]:
        cursor = self._conn.execute(
            "SELECT * FROM conversation_profiles WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else {}

    def upsert_profile(self, conversation_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.get_profile(conversation_id)
        merged = existing.copy()
        merged.update({k: v for k, v in data.items() if v})
        fields = [
            "stage",
            "intent",
            "urgency",
            "contact_name",
            "product_type",
            "product_sku",
            "product_name",
            "inventory_status",
            "style",
            "metal",
            "stone",
            "shape",
            "budget",
            "ring_size",
            "consult_type",
            "requested_date",
            "contact_email",
            "contact_phone",
            "summary",
        ]
        values = [merged.get(field) for field in fields]
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO conversation_profiles (
                        conversation_id, stage, intent, urgency, contact_name, product_type, product_sku,
                        product_name, inventory_status, style, metal,
                        stone, shape, budget, ring_size, consult_type, requested_date,
                        contact_email, contact_phone, summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(conversation_id) DO UPDATE SET
                        intent=excluded.intent,
                        urgency=excluded.urgency,
                        contact_name=excluded.contact_name,
                        product_type=excluded.product_type,
                        product_sku=excluded.product_sku,
                        product_name=excluded.product_name,
                        inventory_status=excluded.inventory_status,
                        style=excluded.style,
                        metal=excluded.metal,
                        stone=excluded.stone,
                        shape=excluded.shape,
                        budget=excluded.budget,
                        ring_size=excluded.ring_size,
                        consult_type=excluded.consult_type,
                        requested_date=excluded.requested_date,
                        contact_email=excluded.contact_email,
                        contact_phone=excluded.contact_phone,
                        summary=excluded.summary,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (conversation_id, *values),
                )
        merged["conversation_id"] = conversation_id
        return merged

    def list_profiles(self, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(
            """
            SELECT * FROM conversation_profiles
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def clear_chat_history(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM messages")
                self._conn.execute("DELETE FROM conversation_profiles")
                self._conn.execute("DELETE FROM conversations")
