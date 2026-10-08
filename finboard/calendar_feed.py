from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "telegram.db"
KST = ZoneInfo("Asia/Seoul")


def init_calendar_schema(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                start_at_utc TEXT NOT NULL,
                end_at_utc TEXT,
                event_url TEXT,
                source TEXT NOT NULL,
                collected_at_utc TEXT NOT NULL,
                UNIQUE(uid, start_at_utc)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_calendar_events_start "
            "ON calendar_events(start_at_utc)"
        )


def _as_kst_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=KST)
    raise ValueError(f"Unsupported calendar event start value: {type(value).__name__}")


def _optional_datetime(value) -> datetime | None:
    if value is None:
        return None
    try:
        return _as_kst_datetime(value).astimezone(timezone.utc)
    except ValueError:
        return None


def sync_calendar(days: int, db_path: Path = DB_PATH, calendar_url: str | None = None) -> int:
    if days < 1:
        raise ValueError("days must be a positive integer")
    load_dotenv(BASE_DIR / ".env")
    feed_url = calendar_url or os.getenv("FINBOARD_CALENDAR_ICS_URL", "").strip()
    if not feed_url:
        raise RuntimeError(
            "Set FINBOARD_CALENDAR_ICS_URL to a public .ics calendar feed before syncing."
        )
    if urlparse(feed_url).scheme not in {"http", "https"}:
        raise ValueError("Calendar feed URL must use http or https.")

    try:
        from icalendar import Calendar
    except ImportError as exc:
        raise RuntimeError(
            "Calendar feed support requires icalendar. Install project dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    request = Request(feed_url, headers={"User-Agent": "Finboard/1.0 (calendar reader)"})
    with urlopen(request, timeout=25) as response:
        calendar = Calendar.from_ical(response.read())

    now = datetime.now(timezone.utc)
    until = now + timedelta(days=days)
    calendar_name = str(calendar.get("X-WR-CALNAME") or "Public calendar")
    collected_at = now.isoformat()
    saved = 0
    init_calendar_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        for event in calendar.walk("VEVENT"):
            start = _as_kst_datetime(event.decoded("dtstart")).astimezone(timezone.utc)
            if start < now or start > until:
                continue
            uid = str(event.get("uid") or "").strip()
            title = str(event.get("summary") or "").strip()
            if not title:
                continue
            if not uid:
                uid = hashlib.sha256(f"{title}|{start.isoformat()}".encode()).hexdigest()
            end = _optional_datetime(event.decoded("dtend") if event.get("dtend") else None)
            event_url = str(event.get("url")) if event.get("url") else None
            description = str(event.get("description") or "").strip() or None
            result = conn.execute(
                """
                INSERT INTO calendar_events (
                    uid, title, description, start_at_utc, end_at_utc,
                    event_url, source, collected_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid, start_at_utc) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    end_at_utc = excluded.end_at_utc,
                    event_url = excluded.event_url,
                    source = excluded.source,
                    collected_at_utc = excluded.collected_at_utc
                """,
                (
                    uid,
                    title,
                    description,
                    start.isoformat(),
                    end.isoformat() if end else None,
                    event_url,
                    calendar_name,
                    collected_at,
                ),
            )
            saved += result.rowcount
    return saved
