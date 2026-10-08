from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAIError
from pydantic import ValidationError

from ai.relevance import analyze_message_with_usage
from news_feeds import DB_PATH, init_news_schema

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

MODEL_NAME = "gpt-5.6-luna"
INPUT_PRICE_PER_MILLION = 0.20
OUTPUT_PRICE_PER_MILLION = 1.20


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate bilingual summaries and event/entity analysis for saved RSS articles."
    )
    parser.add_argument(
        "--days",
        type=int,
        required=True,
        help="Only analyse articles from the last N days (required to control API usage).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        required=True,
        help="Maximum articles to analyse (required to control API usage).",
    )
    args = parser.parse_args()
    if args.days < 1 or args.limit < 1:
        parser.error("--days and --limit must be positive integers.")
    return args


def get_pending_articles(conn, cutoff: str, limit: int):
    return conn.execute(
        """
        SELECT article.id, article.title, article.description, article.news_field
        FROM external_articles AS article
        LEFT JOIN external_article_analysis AS analysis
            ON analysis.article_id = article.id
        WHERE (
                analysis.article_id IS NULL
                OR COALESCE(TRIM(analysis.summary_ko), '') = ''
                OR COALESCE(TRIM(analysis.summary_en), '') = ''
              )
          AND article.published_at_utc >= ?
        ORDER BY article.published_at_utc DESC
        LIMIT ?
        """,
        (cutoff, limit),
    ).fetchall()


def main():
    args = parse_args()
    init_news_schema(DB_PATH)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = get_pending_articles(conn, cutoff, args.limit)

        successful = 0
        failed = 0
        total_input_tokens = 0
        total_cached_tokens = 0
        total_output_tokens = 0
        total_tokens = 0
        total_cost = 0.0

        print(f"Selected {len(rows)} article(s), at most {args.limit}, from the last {args.days} day(s).")
        for row in rows:
            text = "\n".join(
                value.strip()
                for value in (row["title"], row["description"])
                if isinstance(value, str) and value.strip()
            )
            try:
                result, usage = analyze_message_with_usage(text)
            except (OpenAIError, ValidationError) as exc:
                failed += 1
                print(f"Could not analyse article {row['id']}: {exc}")
                continue

            entities_json = json.dumps(
                [entity.model_dump() for entity in result.entities],
                ensure_ascii=False,
            )
            cost = (
                usage["input_tokens"] / 1_000_000 * INPUT_PRICE_PER_MILLION
                + usage["output_tokens"] / 1_000_000 * OUTPUT_PRICE_PER_MILLION
            )
            conn.execute(
                """
                INSERT INTO external_article_analysis (
                    article_id, relevant, relevance_score, category, news_field,
                    event_type, information_status, summary_ko, summary_en,
                    event_date_kst, entities_json, needs_review, model,
                    processed_at_utc, input_tokens, cached_input_tokens,
                    output_tokens, total_tokens, estimated_cost_usd
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    relevant = excluded.relevant,
                    relevance_score = excluded.relevance_score,
                    category = excluded.category,
                    news_field = excluded.news_field,
                    event_type = excluded.event_type,
                    information_status = excluded.information_status,
                    summary_ko = excluded.summary_ko,
                    summary_en = excluded.summary_en,
                    event_date_kst = excluded.event_date_kst,
                    entities_json = excluded.entities_json,
                    needs_review = excluded.needs_review,
                    model = excluded.model,
                    processed_at_utc = excluded.processed_at_utc,
                    input_tokens = COALESCE(external_article_analysis.input_tokens, 0) + excluded.input_tokens,
                    cached_input_tokens = COALESCE(external_article_analysis.cached_input_tokens, 0) + excluded.cached_input_tokens,
                    output_tokens = COALESCE(external_article_analysis.output_tokens, 0) + excluded.output_tokens,
                    total_tokens = COALESCE(external_article_analysis.total_tokens, 0) + excluded.total_tokens,
                    estimated_cost_usd = COALESCE(external_article_analysis.estimated_cost_usd, 0) + excluded.estimated_cost_usd
                """,
                (
                    row["id"],
                    int(result.relevant),
                    result.relevance_score,
                    result.category,
                    result.news_field,
                    result.event_type,
                    result.information_status,
                    result.summary_ko,
                    result.summary_en,
                    result.event_date_kst,
                    entities_json,
                    int(result.needs_review),
                    MODEL_NAME,
                    datetime.now(timezone.utc).isoformat(),
                    usage["input_tokens"],
                    usage["cached_input_tokens"],
                    usage["output_tokens"],
                    usage["total_tokens"],
                    cost,
                ),
            )
            conn.commit()
            successful += 1
            total_input_tokens += usage["input_tokens"]
            total_cached_tokens += usage["cached_input_tokens"]
            total_output_tokens += usage["output_tokens"]
            total_tokens += usage["total_tokens"]
            total_cost += cost

        print(
            f"Completed: {successful} analysed, {failed} failed; "
            f"{total_input_tokens:,} input tokens ({total_cached_tokens:,} cached), "
            f"{total_output_tokens:,} output tokens, {total_tokens:,} total tokens, "
            f"estimated cost ${total_cost:.6f}."
        )
        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
