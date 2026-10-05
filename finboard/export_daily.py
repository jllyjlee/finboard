from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from database import get_connection, init_db

OUTPUT_DIR = Path("exports")


def parse_args():
    parser = argparse.ArgumentParser(description="Export Telegram messages as daily TXT")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Korea date, YYYY-MM-DD",
    )
    parser.add_argument(
        "--channel",
        default="ALL",
        help='Channel name from channels.json, or "ALL"',
    )
    return parser.parse_args()


def main():
    args = parse_args()
    init_db()

    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit("--date must be YYYY-MM-DD") from exc

    params = [f"{args.date}%"]
    where = "message_date_kst LIKE ?"

    if args.channel != "ALL":
        where += " AND channel_name = ?"
        params.append(args.channel)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT channel_name, message_date_kst, text
            FROM messages
            WHERE {where}
            ORDER BY message_date_kst ASC
            """,
            params,
        ).fetchall()

    OUTPUT_DIR.mkdir(exist_ok=True)
    safe_channel = args.channel.replace("/", "_")
    out_path = OUTPUT_DIR / f"telegram_{safe_channel}_{args.date}.txt"

    lines = [
        "TELEGRAM DAILY NEWS",
        f"Channel: {args.channel}",
        f"Date: {args.date}",
        "=" * 60,
        "",
    ]

    for row in rows:
        local_dt = datetime.fromisoformat(row["message_date_kst"])
        lines.append(f"DATE: {local_dt.isoformat()}")
        lines.append(row["text"] or "")
        lines.append("-" * 60)
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Exported {len(rows)} messages -> {out_path}")


if __name__ == "__main__":
    main()
