import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "telegram.db"

print(f"\nInspecting: {DB_PATH}")
print("=" * 60)

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

tables = cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type='table'
    ORDER BY name
""").fetchall()

print("\nTABLES:")

for table in tables:
    print(" -", table[0])

for table in tables:
    table_name = table[0]

    print("\n")
    print("=" * 60)
    print(f"TABLE: {table_name}")
    print("=" * 60)

    columns = cursor.execute(
        f'PRAGMA table_info("{table_name}")'
    ).fetchall()

    print("\nCOLUMNS:")

    for column in columns:
        print(
            f"  {column[1]:25} "
            f"{column[2]}"
        )

    try:
        rows = cursor.execute(
            f'SELECT * FROM "{table_name}" LIMIT 3'
        ).fetchall()

        print("\nSAMPLE ROWS:")

        for row in rows:
            print(row)

    except Exception as e:
        print("Could not read sample rows:", e)

conn.close()