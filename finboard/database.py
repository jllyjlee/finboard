from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "telegram.db"
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                telegram_message_id INTEGER NOT NULL,
                message_date_utc TEXT NOT NULL,
                message_date_kst TEXT NOT NULL,
                text TEXT,
                sender_id INTEGER,
                is_forwarded INTEGER NOT NULL DEFAULT 0,
                reply_to_msg_id INTEGER,
                has_media INTEGER NOT NULL DEFAULT 0,
                media_type TEXT,
                first_url TEXT,
                shared_urls_json TEXT,
                collected_at_utc TEXT NOT NULL,
                UNIQUE(chat_id, telegram_message_id)
            )
            """
        )

        message_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(messages)")
        }
        if "shared_urls_json" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN shared_urls_json TEXT")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_date_kst "
            "ON messages(message_date_kst DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_channel "
            "ON messages(channel_name)"
        )


def save_message(record: dict) -> bool:
    """Insert a Telegram message. Returns True if inserted, False if duplicate."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO messages (
                chat_id,
                channel_name,
                telegram_message_id,
                message_date_utc,
                message_date_kst,
                text,
                sender_id,
                is_forwarded,
                reply_to_msg_id,
                has_media,
                media_type,
                first_url,
                shared_urls_json,
                collected_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["chat_id"],
                record["channel_name"],
                record["telegram_message_id"],
                record["message_date_utc"],
                record["message_date_kst"],
                record.get("text"),
                record.get("sender_id"),
                int(record.get("is_forwarded", False)),
                record.get("reply_to_msg_id"),
                int(record.get("has_media", False)),
                record.get("media_type"),
                record.get("first_url"),
                record.get("shared_urls_json"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        inserted = cur.rowcount == 1
        shared_urls = record.get("shared_urls_json")
        if not inserted and shared_urls and shared_urls != "[]":
            conn.execute(
                """
                UPDATE messages
                SET shared_urls_json = ?, first_url = COALESCE(first_url, ?)
                WHERE chat_id = ? AND telegram_message_id = ?
                """,
                (
                    shared_urls,
                    record.get("first_url"),
                    record["chat_id"],
                    record["telegram_message_id"],
                ),
            )
        return inserted
