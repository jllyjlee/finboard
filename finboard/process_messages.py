import argparse
import sqlite3
import json

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from openai import OpenAIError
from pydantic import ValidationError


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
DB_PATH = BASE_DIR / "data" / "telegram.db"


# ---------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------

load_dotenv(ENV_PATH)


# ---------------------------------------------------------
# Import our existing AI processor
# ---------------------------------------------------------

from ai.relevance import analyze_message_with_usage


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

MODEL_NAME = "gpt-5.6-luna"

# GPT-5.6 Luna pricing per 1 million tokens
INPUT_PRICE_PER_MILLION = 0.20
OUTPUT_PRICE_PER_MILLION = 1.20

def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyse unprocessed Telegram messages in a bounded date range."
    )
    parser.add_argument(
        "--days",
        type=int,
        required=True,
        help="Only process messages from the last N days (required to control API usage).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        required=True,
        help="Maximum messages to analyse (required to control API usage).",
    )
    args = parser.parse_args()
    if args.days < 1 or args.limit < 1:
        parser.error("--days and --limit must be positive integers.")
    return args


args = parse_args()


# ---------------------------------------------------------
# Connect to database
# ---------------------------------------------------------

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(DB_PATH)

# Allows us to access columns like:
# row["text"]
# instead of row[6]
conn.row_factory = sqlite3.Row

cursor = conn.cursor()

# ---------------------------------------------------------
# Create AI analysis table
# ---------------------------------------------------------

cursor.execute("""
CREATE TABLE IF NOT EXISTS ai_message_analysis (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    message_id INTEGER NOT NULL UNIQUE,

    relevant INTEGER NOT NULL,
    relevance_score INTEGER NOT NULL,

    category TEXT,
    event_type TEXT,
    information_status TEXT,

    entities_json TEXT,

    needs_review INTEGER NOT NULL,

    model TEXT,
    processed_at_utc TEXT,

    input_tokens INTEGER,
    cached_input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    estimated_cost_usd REAL,

    FOREIGN KEY (message_id)
        REFERENCES messages(id)
)
""")

conn.commit()


# ---------------------------------------------------------
# Ensure token-usage columns exist
# ---------------------------------------------------------

existing_columns = {
    row[1]
    for row in cursor.execute(
        "PRAGMA table_info(ai_message_analysis)"
    ).fetchall()
}


columns_to_add = {
    "input_tokens": "INTEGER",
    "cached_input_tokens": "INTEGER",
    "output_tokens": "INTEGER",
    "total_tokens": "INTEGER",
    "estimated_cost_usd": "REAL",
    "news_field": "TEXT",
    "summary_ko": "TEXT",
    "summary_en": "TEXT",
    "event_date_kst": "TEXT",
}


for column_name, column_type in columns_to_add.items():

    if column_name not in existing_columns:

        cursor.execute(
            f"""
            ALTER TABLE ai_message_analysis
            ADD COLUMN {column_name} {column_type}
            """
        )


conn.commit()


# ---------------------------------------------------------
# Find messages that have NOT been processed yet
# ---------------------------------------------------------

messages = cursor.execute("""
SELECT
    m.id,
    m.chat_id,
    m.channel_name,
    m.telegram_message_id,
    m.message_date_kst,
    m.text,
    m.first_url

FROM messages AS m

LEFT JOIN ai_message_analysis AS a
    ON a.message_id = m.id

WHERE
    (
        a.message_id IS NULL
        OR COALESCE(TRIM(a.news_field), '') = ''
        OR COALESCE(TRIM(a.summary_ko), '') = ''
        OR COALESCE(TRIM(a.summary_en), '') = ''
    )
    AND m.text IS NOT NULL
    AND TRIM(m.text) != ''
    AND m.message_date_kst >= ?

ORDER BY m.id ASC

LIMIT ?
""", (
    (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=args.days)).isoformat(),
    args.limit,
)).fetchall()


print()
print("=" * 70)
print("FINBOARD AI MESSAGE PROCESSOR")
print("=" * 70)

print(f"Messages selected: {len(messages)}")

print()


# ---------------------------------------------------------
# Process messages
# ---------------------------------------------------------

success_count = 0
error_count = 0

run_input_tokens = 0
run_cached_tokens = 0
run_output_tokens = 0
run_total_tokens = 0
run_cost_usd = 0.0


for number, message in enumerate(messages, start=1):

    message_id = message["id"]
    channel_name = message["channel_name"]
    text = message["text"]

    print()
    print("=" * 70)

    print(
        f"[{number}/{len(messages)}] "
        f"Processing message ID {message_id}"
    )

    print(f"Channel: {channel_name}")

    print("-" * 70)

    # Display a short preview so the terminal stays readable
    preview = text.replace("\n", " ")

    if len(preview) > 250:
        preview = preview[:250] + "..."

    print("Message:")
    print(preview)

    print("-" * 70)

    try:

        # -------------------------------------------------
        # Send message to OpenAI
        # -------------------------------------------------

        result, usage = analyze_message_with_usage(text)

        input_tokens = usage["input_tokens"]
        cached_input_tokens = usage["cached_input_tokens"]
        output_tokens = usage["output_tokens"]
        total_tokens = usage["total_tokens"]


        estimated_cost_usd = (
            (input_tokens / 1_000_000)
            * INPUT_PRICE_PER_MILLION
            +
            (output_tokens / 1_000_000)
            * OUTPUT_PRICE_PER_MILLION
        )

        # Add API usage to totals immediately
        run_input_tokens += input_tokens
        run_cached_tokens += cached_input_tokens
        run_output_tokens += output_tokens
        run_total_tokens += total_tokens
        run_cost_usd += estimated_cost_usd

        # -------------------------------------------------
        # Convert entities into JSON for SQLite
        # -------------------------------------------------

        entities = [
            entity.model_dump()
            for entity in result.entities
        ]

        entities_json = json.dumps(
            entities,
            ensure_ascii=False
        )


        # -------------------------------------------------
        # Save AI output
        # -------------------------------------------------

        cursor.execute("""
INSERT INTO ai_message_analysis (

    message_id,

    relevant,
    relevance_score,

    category,
    news_field,
    event_type,
    information_status,
    summary_ko,
    summary_en,
    event_date_kst,

    entities_json,

    needs_review,

    model,
    processed_at_utc,

    input_tokens,
    cached_input_tokens,
    output_tokens,
    total_tokens,
    estimated_cost_usd

)

VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(message_id) DO UPDATE SET
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
    input_tokens = COALESCE(ai_message_analysis.input_tokens, 0) + excluded.input_tokens,
    cached_input_tokens = COALESCE(ai_message_analysis.cached_input_tokens, 0) + excluded.cached_input_tokens,
    output_tokens = COALESCE(ai_message_analysis.output_tokens, 0) + excluded.output_tokens,
    total_tokens = COALESCE(ai_message_analysis.total_tokens, 0) + excluded.total_tokens,
    estimated_cost_usd = COALESCE(ai_message_analysis.estimated_cost_usd, 0) + excluded.estimated_cost_usd
""", (

    message_id,

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

    input_tokens,
    cached_input_tokens,
    output_tokens,
    total_tokens,
    estimated_cost_usd,

))

        conn.commit()

        success_count += 1
        

        # -------------------------------------------------
        # Display result
        # -------------------------------------------------

        print(
            f"Relevant: {result.relevant}"
        )

        print(
            f"Score: {result.relevance_score}"
        )

        print(
            f"Category: {result.category}"
        )

        print(
            f"Event type: {result.event_type}"
        )

        print(
            f"Information status: "
            f"{result.information_status}"
        )

        print(
            f"Needs review: "
            f"{result.needs_review}"
        )


        print("\nEntities:")

        if not result.entities:

            print("  None")

        else:

            for entity in result.entities:

                print(
                    " ",
                    entity.mention,
                    "->",
                    entity.normalized_name,
                    "|",
                    entity.entity_type,
                    "| ticker:",
                    entity.ticker_candidate,
                    "| exchange:",
                    entity.exchange,
                    "| confidence:",
                    entity.ticker_confidence,
                )

                print()
                print("TOKEN USAGE")
                print("-" * 70)

                print(
                    f"Input tokens:        {input_tokens:,}"
                )

                print(
                    f"Cached input tokens: {cached_input_tokens:,}"
                )

                print(
                    f"Output tokens:       {output_tokens:,}"
                )

                print(
                    f"Total tokens:        {total_tokens:,}"
                )

                print(
                    f"Estimated cost:      ${estimated_cost_usd:.6f}"
                )

    except (OpenAIError, ValidationError) as e:

        error_count += 1

        print()
        print("ERROR:")
        print(e)


# ---------------------------------------------------------
# Close database
# ---------------------------------------------------------

conn.close()


# ---------------------------------------------------------
# Summary
# ---------------------------------------------------------

print()
print("=" * 70)
print("PROCESSING COMPLETE")
print("=" * 70)

print(f"Successful: {success_count}")
print(f"Errors:     {error_count}")
print(f"Requested date window: last {args.days} day(s), at most {args.limit} messages")

print()
print("RUN TOKEN USAGE")
print("-" * 70)

print(
    f"Input tokens:        {run_input_tokens:,}"
)

print(
    f"Cached input tokens: {run_cached_tokens:,}"
)

print(
    f"Output tokens:       {run_output_tokens:,}"
)

print(
    f"Total tokens:        {run_total_tokens:,}"
)

print(
    f"Estimated API cost:  ${run_cost_usd:.6f}"
)

if success_count > 0:

    print(
        f"Average cost/message: "
        f"${run_cost_usd / success_count:.6f}"
    )

if error_count:
    raise SystemExit(1)