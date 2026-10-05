import sqlite3
import json


DB_PATH = "data/telegram.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

cursor = conn.cursor()


rows = cursor.execute("""
SELECT

    m.id AS message_id,
    m.channel_name,
    m.message_date_kst,
    m.text,
    m.first_url,

    a.relevant,
    a.relevance_score,
    a.category,
    a.event_type,
    a.information_status,
    a.entities_json,
    a.needs_review,
    a.model

FROM ai_message_analysis AS a

JOIN messages AS m
    ON m.id = a.message_id

ORDER BY m.id ASC

LIMIT 10
""").fetchall()


print()
print("=" * 90)
print("FINBOARD AI REVIEW")
print("=" * 90)


for number, row in enumerate(rows, start=1):

    print()
    print("=" * 90)

    print(
        f"[{number}/{len(rows)}] "
        f"MESSAGE ID: {row['message_id']}"
    )

    print(
        f"Channel: {row['channel_name']}"
    )

    print(
        f"Date: {row['message_date_kst']}"
    )

    if row["first_url"]:
        print(
            f"URL: {row['first_url']}"
        )

    print()
    print("ORIGINAL MESSAGE")
    print("-" * 90)

    print(row["text"])

    print()
    print("AI ANALYSIS")
    print("-" * 90)

    print(
        f"Relevant:           "
        f"{bool(row['relevant'])}"
    )

    print(
        f"Relevance score:    "
        f"{row['relevance_score']}"
    )

    print(
        f"Category:           "
        f"{row['category']}"
    )

    print(
        f"Event type:         "
        f"{row['event_type']}"
    )

    print(
        f"Information status: "
        f"{row['information_status']}"
    )

    print(
        f"Needs review:       "
        f"{bool(row['needs_review'])}"
    )

    print(
        f"Model:              "
        f"{row['model']}"
    )

    print()
    print("ENTITIES")
    print("-" * 90)

    entities = json.loads(
        row["entities_json"]
    )

    if not entities:

        print("None")

    else:

        for entity in entities:

            print(
                f"- {entity['mention']}"
            )

            print(
                f"    Normalized: "
                f"{entity['normalized_name']}"
            )

            print(
                f"    Type: "
                f"{entity['entity_type']}"
            )

            print(
                f"    Ticker: "
                f"{entity['ticker_candidate']}"
            )

            print(
                f"    Exchange: "
                f"{entity['exchange']}"
            )

            print(
                f"    Confidence: "
                f"{entity['ticker_confidence']}"
            )

    print()


conn.close()