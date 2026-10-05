import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

BASE_DIR = Path(__file__).resolve().parent
SESSION_DIR = BASE_DIR / "sessions"


async def main():
    load_dotenv(BASE_DIR / ".env")

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE", "").strip()

    if not api_id or not api_hash:
        raise RuntimeError("Telegram API details missing from .env")

    client = TelegramClient(
        str(SESSION_DIR / "finance_dashboard"),
        int(api_id),
        api_hash
    )

    if phone:
        await client.start(phone=phone)
    else:
        await client.start()

    rooms = []

    try:
        async for dialog in client.iter_dialogs():

            entity = dialog.entity

            # Only groups + channels
            # Excludes individual/private 1-to-1 chats
            if isinstance(entity, (Channel, Chat)):

                # Skip rooms the account has already left
                if getattr(entity, "left", False):
                    continue

                rooms.append({
                    "name": dialog.name,
                    "entity": str(dialog.id)
                })

                print(
                    f"{dialog.id} | {dialog.name}"
                )

    finally:
        await client.disconnect()

    with open(
        BASE_DIR / "channels_all.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            rooms,
            f,
            ensure_ascii=False,
            indent=2
        )

    print()
    print(f"Found {len(rooms)} groups/channels.")
    print("Saved to channels_all.json")


if __name__ == "__main__":
    asyncio.run(main())