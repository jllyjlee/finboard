from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "telegram.db"
FEED_URL = "https://news.google.com/rss/search"

# Topic buckets intentionally remain broad enough for useful dashboard filters.
NEWS_FIELDS = {
    "business_finance": ("business finance", "기업 금융"),
    "economy": ("economy economic policy", "경제 경제정책"),
    "politics": ("politics government", "정치 정부"),
    "healthcare": ("healthcare medical research", "의료 보건 의학"),
    "ai_technology": ("artificial intelligence technology", "인공지능 기술"),
    "science": ("science research", "과학 연구"),
    "sports": ("sports", "스포츠"),
    "geopolitics": ("geopolitics international relations", "지정학 국제 관계"),
    "energy_commodities": ("energy commodities", "에너지 원자재"),
    "crypto": ("cryptocurrency digital assets", "암호화폐 디지털 자산"),
}

FEED_LOCALES = (
    {"language": "en", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"language": "ko", "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
)


def init_news_schema(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS external_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT,
                published_at_utc TEXT,
                news_field TEXT NOT NULL,
                source TEXT,
                source_language TEXT NOT NULL,
                collected_at_utc TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_external_articles_date "
            "ON external_articles(published_at_utc DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_external_articles_field "
            "ON external_articles(news_field)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS external_article_analysis (
                article_id INTEGER PRIMARY KEY,
                relevant INTEGER NOT NULL,
                relevance_score INTEGER NOT NULL,
                category TEXT,
                news_field TEXT,
                event_type TEXT,
                information_status TEXT,
                summary_ko TEXT,
                summary_en TEXT,
                event_date_kst TEXT,
                entities_json TEXT NOT NULL,
                needs_review INTEGER NOT NULL,
                model TEXT,
                processed_at_utc TEXT NOT NULL,
                input_tokens INTEGER,
                cached_input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                estimated_cost_usd REAL,
                FOREIGN KEY (article_id) REFERENCES external_articles(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_external_article_analysis_event "
            "ON external_article_analysis(event_date_kst)"
        )


def build_feed_url(query: str, locale: dict[str, str]) -> str:
    params = {
        "q": query,
        "hl": locale["hl"],
        "gl": locale["gl"],
        "ceid": locale["ceid"],
    }
    return f"{FEED_URL}?{urlencode(params)}"


def fetch_feed(url: str, timeout: int = 20) -> list[dict[str, str | None]]:
    request = Request(url, headers={"User-Agent": "Finboard/1.0 (RSS reader)"})
    with urlopen(request, timeout=timeout) as response:
        root = ET.fromstring(response.read())

    articles = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        published = item.findtext("pubDate")
        published_at = None
        if published:
            published_at = parsedate_to_datetime(published).astimezone(timezone.utc).isoformat()
        source = item.findtext("source")
        description = item.findtext("description")
        articles.append(
            {
                "title": title,
                "url": link,
                "description": description,
                "published_at_utc": published_at,
                "source": source.strip() if source else None,
            }
        )
    return articles


def sync_news(days: int, db_path: Path = DB_PATH) -> tuple[int, list[str]]:
    if days < 1:
        raise ValueError("days must be a positive integer")
    init_news_schema(db_path)
    cutoff = datetime.now(timezone.utc).timestamp() - days * 24 * 60 * 60
    collected_at = datetime.now(timezone.utc).isoformat()
    inserted = 0
    failures = []

    with sqlite3.connect(db_path) as conn:
        for news_field, queries in NEWS_FIELDS.items():
            for locale, query in zip(FEED_LOCALES, queries, strict=True):
                url = build_feed_url(query, locale)
                try:
                    articles = fetch_feed(url)
                except (OSError, ET.ParseError, ValueError) as exc:
                    failures.append(f"{news_field}/{locale['language']}: {exc}")
                    continue

                for article in articles:
                    published = article["published_at_utc"]
                    if not published or datetime.fromisoformat(published).timestamp() < cutoff:
                        continue
                    result = conn.execute(
                        """
                        INSERT OR IGNORE INTO external_articles (
                            url, title, description, published_at_utc,
                            news_field, source, source_language, collected_at_utc
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            article["url"],
                            article["title"],
                            article["description"],
                            published,
                            news_field,
                            article["source"],
                            locale["language"],
                            collected_at,
                        ),
                    )
                    inserted += result.rowcount

    if len(failures) == len(NEWS_FIELDS) * len(FEED_LOCALES):
        raise RuntimeError("All public news feeds failed: " + "; ".join(failures))
    return inserted, failures
