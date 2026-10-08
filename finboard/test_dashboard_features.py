from __future__ import annotations

import io
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from calendar_feed import init_calendar_schema, sync_calendar
from collector import message_urls
from dashboard import briefing_source_groups, format_label, read_data, telegram_report_urls
from database import init_db, save_message
from market_data import Asset, asset_for_entity, fetch_quotes, quote_symbol_for_entity
from news_feeds import fetch_feed, init_news_schema, sync_news
from portfolio import PORTFOLIO_EXAMPLES, allocation_total
from process_news import get_pending_articles


def test_read_data_combines_messages_articles_and_calendar(tmp_path: Path):
    db_path = tmp_path / "finboard.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY, chat_id INTEGER, channel_name TEXT,
                telegram_message_id INTEGER, message_date_kst TEXT,
                text TEXT, first_url TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE ai_message_analysis (
                message_id INTEGER, relevant INTEGER, relevance_score INTEGER,
                category TEXT, news_field TEXT, event_type TEXT,
                information_status TEXT, entities_json TEXT, needs_review INTEGER,
                summary_ko TEXT, summary_en TEXT, event_date_kst TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO messages VALUES (1, -100123, 'Finance room', 42, ?, ?, ?)",
            ("2026-10-07T10:00:00+09:00", "삼성전자 실적 발표", "https://example.test/post"),
        )
        conn.execute(
            """
            INSERT INTO ai_message_analysis (
                message_id, relevant, relevance_score, category, news_field,
                event_type, information_status, entities_json, needs_review,
                summary_ko, summary_en, event_date_kst
            )
            VALUES (1, 1, 90, 'earnings', 'business_finance', 'earnings', 'reported',
                    '[]', 0, '실적 발표', 'Earnings announced', '2026-10-08')
            """
        )

    init_news_schema(db_path)
    init_calendar_schema(db_path)
    published = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO external_articles (
                url, title, description, published_at_utc, news_field, source,
                source_language, collected_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://example.test/news",
                "AI sector update",
                "A new development.",
                published,
                "ai_technology",
                "Example News",
                "en",
                published,
            ),
        )
        article_id = conn.execute("SELECT id FROM external_articles").fetchone()[0]
        conn.execute(
            """
            INSERT INTO external_article_analysis (
                article_id, relevant, relevance_score, news_field,
                summary_ko, summary_en, entities_json, needs_review, processed_at_utc
            )
            VALUES (?, 1, 80, 'ai_technology', 'AI 소식', 'AI update', '[]', 0, ?)
            """,
            (article_id, published),
        )
        conn.execute(
            """
            INSERT INTO calendar_events (
                uid, title, description, start_at_utc, event_url, source, collected_at_utc
            )
            VALUES ('event-1', 'Central bank meeting', '', ?, 'https://example.test/event',
                    'Public calendar', ?)
            """,
            ((datetime.now(timezone.utc) + timedelta(days=2)).isoformat(), published),
        )

    data, has_ai = read_data(db_path)

    assert has_ai
    assert len(data) == 3
    assert set(data["source_type"]) == {"Telegram", "News", "Calendar"}
    news_row = data.loc[data["source_type"] == "News"].iloc[0]
    assert news_row["summary_en"] == "AI update"
    assert news_row["source_link"] == "https://example.test/news"
    calendar_row = data.loc[data["source_type"] == "Calendar"].iloc[0]
    assert calendar_row["event_date_kst"] is not None
    assert not calendar_row["requires_ai"]


def test_read_data_supports_rss_without_telegram_collector(tmp_path: Path):
    db_path = tmp_path / "rss-only.db"
    init_news_schema(db_path)
    published = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO external_articles (
                url, title, published_at_utc, news_field, source,
                source_language, collected_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://example.test/politics",
                "Politics headline",
                published,
                "politics",
                "Example News",
                "en",
                published,
            ),
        )

    data, has_ai = read_data(db_path)

    assert len(data) == 1
    assert data.iloc[0]["source_type"] == "News"
    assert data.iloc[0]["news_field"] == "politics"
    assert not has_ai


def test_briefing_groups_telegram_before_external_coverage():
    day = pd.DataFrame(
        {
            "source_type": ["News", "Telegram", "Calendar"],
            "relevance_score": [99, 20, None],
        }
    )

    groups = briefing_source_groups(day)

    assert [source_type for source_type, _ in groups] == [
        "Telegram",
        "News",
        "Calendar",
    ]
    assert groups[0][1].iloc[0]["relevance_score"] == 20


def test_telegram_report_links_include_all_stored_and_plain_text_urls():
    row = pd.Series(
        {
            "shared_urls_json": '["https://reports.example/one", "https://reports.example/two"]',
            "text": "Update: https://reports.example/three.",
            "first_url": "https://reports.example/one",
        }
    )

    assert telegram_report_urls(row) == [
        "https://reports.example/one",
        "https://reports.example/two",
        "https://reports.example/three",
    ]


def test_collector_extracts_plain_and_hidden_telegram_links():
    message = SimpleNamespace(
        raw_text="New report: https://reports.example/one.",
        entities=[
            SimpleNamespace(url="https://reports.example/two"),
            SimpleNamespace(url="https://reports.example/one"),
        ],
    )

    assert message_urls(message) == [
        "https://reports.example/one",
        "https://reports.example/two",
    ]


def test_telegram_database_adds_shared_link_storage_to_legacy_schema(tmp_path: Path):
    db_path = tmp_path / "telegram.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE messages (
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
                collected_at_utc TEXT NOT NULL,
                UNIQUE(chat_id, telegram_message_id)
            )
            """
        )

    with patch("database.DB_PATH", db_path):
        init_db()
        record = {
            "chat_id": -100123,
            "channel_name": "Finance room",
            "telegram_message_id": 99,
            "message_date_utc": "2026-10-07T10:00:00+00:00",
            "message_date_kst": "2026-10-07T19:00:00+09:00",
            "text": "Report",
            "first_url": "https://reports.example/one",
            "shared_urls_json": '["https://reports.example/one"]',
        }
        assert save_message(record)
        record["shared_urls_json"] = (
            '["https://reports.example/one", "https://reports.example/hidden"]'
        )
        assert not save_message(record)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        saved_links = conn.execute(
            "SELECT shared_urls_json FROM messages WHERE telegram_message_id = 99"
        ).fetchone()[0]
    assert "shared_urls_json" in columns
    assert saved_links == (
        '["https://reports.example/one", "https://reports.example/hidden"]'
    )


def test_news_feed_xml_and_sync_are_offline_and_deduplicate(tmp_path: Path):
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel><item>
      <title>Markets rise</title><link>https://example.test/story</link>
      <description>Market story</description><pubDate>Wed, 07 Oct 2026 10:00:00 GMT</pubDate>
      <source>Example News</source>
    </item></channel></rss>"""
    with patch("news_feeds.urlopen", return_value=io.BytesIO(xml)):
        article = fetch_feed("https://example.test/feed")[0]

    assert article["title"] == "Markets rise"
    assert article["source"] == "Example News"

    article["published_at_utc"] = datetime.now(timezone.utc).isoformat()
    with patch("news_feeds.fetch_feed", return_value=[article]) as fetch:
        inserted, failures = sync_news(2, tmp_path / "news.db")

    assert inserted == 1
    assert failures == []
    assert fetch.call_count == 20


def test_news_ai_queue_respects_date_window_and_retries_missing_translation(tmp_path: Path):
    db_path = tmp_path / "queue.db"
    init_news_schema(db_path)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=10)).isoformat()
    recent = (now - timedelta(days=1)).isoformat()
    cutoff = (now - timedelta(days=5)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for url, title, published in (
            ("https://example.test/new", "new", recent),
            ("https://example.test/old", "old", old),
            ("https://example.test/complete", "complete", recent),
            ("https://example.test/missing-summary", "missing-summary", recent),
        ):
            conn.execute(
                """
                INSERT INTO external_articles (
                    url, title, published_at_utc, news_field, source,
                    source_language, collected_at_utc
                )
                VALUES (?, ?, ?, 'economy', 'Example', 'en', ?)
                """,
                (url, title, published, recent),
            )
        article_ids = dict(
            conn.execute("SELECT url, id FROM external_articles").fetchall()
        )
        conn.execute(
            """
            INSERT INTO external_article_analysis (
                article_id, relevant, relevance_score, entities_json,
                needs_review, processed_at_utc, summary_ko, summary_en
            )
            VALUES (?, 1, 70, '[]', 0, ?, '요약', 'Summary')
            """,
            (article_ids["https://example.test/complete"], recent),
        )
        conn.execute(
            """
            INSERT INTO external_article_analysis (
                article_id, relevant, relevance_score, entities_json,
                needs_review, processed_at_utc, summary_ko, summary_en
            )
            VALUES (?, 1, 70, '[]', 0, ?, '요약', '')
            """,
            (article_ids["https://example.test/missing-summary"], recent),
        )

        pending = get_pending_articles(conn, cutoff, 10)

    assert {row["title"] for row in pending} == {"new", "missing-summary"}
    assert len(pending) == 2


def test_calendar_sync_imports_only_the_bounded_future_window(tmp_path: Path):
    event_day = (datetime.now(timezone.utc) + timedelta(days=2)).date().strftime("%Y%m%d")
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "X-WR-CALNAME:Public events\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-2\r\n"
        f"DTSTART;VALUE=DATE:{event_day}\r\n"
        "SUMMARY:Policy meeting\r\n"
        "URL:https://example.test/calendar-event\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    ).encode()
    with patch("calendar_feed.urlopen", return_value=io.BytesIO(ics)):
        saved = sync_calendar(
            5,
            tmp_path / "calendar.db",
            calendar_url="https://example.test/events.ics",
        )
    assert saved == 1


def test_quote_mapping_and_watchlist_quotes_without_network():
    assert quote_symbol_for_entity("005930", "KRX") == "005930.KS"
    assert quote_symbol_for_entity("NVDA", "NASDAQ") == "NVDA"
    asset = asset_for_entity(
        {
            "ticker_candidate": "NVDA",
            "exchange": "NASDAQ",
            "normalized_name": "NVIDIA",
        }
    )
    assert asset and asset.yahoo_symbol == "NVDA"

    index = pd.to_datetime(["2026-10-06", "2026-10-07"])
    values = pd.DataFrame(
        {"Close": [100.0, 105.0]},
        index=index,
    )
    fake_yfinance = SimpleNamespace(
        download=MagicMock(
            return_value=pd.concat({"NVDA": values}, axis=1)
        )
    )
    with patch.dict(sys.modules, {"yfinance": fake_yfinance}):
        quotes = fetch_quotes((Asset("NVDA", "NVIDIA", "US", "USD", "NVDA"),))

    assert quotes[0]["price"] == 105.0
    assert abs(quotes[0]["change_pct"] - 5) < 1e-9


def test_portfolio_profiles_are_balanced_and_labels_are_readable():
    assert [allocation_total(profile) for profile in PORTFOLIO_EXAMPLES] == [100, 100, 100]
    assert format_label("ai_technology") == "Ai Technology"
