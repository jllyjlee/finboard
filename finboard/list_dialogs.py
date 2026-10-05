from __future__ import annotations

import asyncio
import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

BASE_DIR = Path(__file__).resolve().parent
SESSION_DIR = BASE_DIR / "sessions"


async def main():
    load_dotenv(BASE_DIR / ".env")

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE", "").strip()

    if not api_id or not api_hash:
        raise RuntimeError("Fill in .env first.")

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        str(SESSION_DIR / "finance_dashboard"),
        int(api_id),
        api_hash,
    )

    if phone:
        await client.start(phone=phone)
    else:
        await client.start()

    rows = []

    try:
        print("\nYour Telegram dialogs:\n")
        async for dialog in client.iter_dialogs():
            entity_type = type(dialog.entity).__name__
            print(f"{dialog.id:>16} | {entity_type:<20} | {dialog.name}")

            rows.append(
                {
                    "dialog_id": dialog.id,
                    "name": dialog.name,
                    "entity_type": entity_type,
                }
            )
    finally:
        await client.disconnect()

    with open(BASE_DIR / "dialogs.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["dialog_id", "name", "entity_type"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\nSaved: dialogs.csv")


if __name__ == "__main__":
    asyncio.run(main())
