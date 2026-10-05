from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telethon import TelegramClient, events

from database import init_db, save_message

KST = ZoneInfo("Asia/Seoul")
URL_RE = re.compile(r"https?://\S+")

BASE_DIR = Path(__file__).resolve().parent
SESSION_DIR = BASE_DIR / "sessions"
CHANNELS_FILE = BASE_DIR / "channels.json"


def load_settings():
    load_dotenv(BASE_DIR / ".env")

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE", "").strip()

    if not api_id or not api_hash:
        raise RuntimeError(
            "Missing TELEGRAM_API_ID / TELEGRAM_API_HASH. "
            "Copy .env.example to .env and fill in your Telegram API credentials."
        )

    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    return int(api_id), api_hash, phone


def load_channels() -> list[dict]:
    if not CHANNELS_FILE.exists():
        raise RuntimeError("channels.json not found.")

    channels = json.loads(CHANNELS_FILE.read_text(encoding="utf-8"))

    if not isinstance(channels, list) or not channels:
        raise RuntimeError("channels.json must contain at least one channel.")

    return channels


def normalize_entity(value):
    """Allow either usernames/links as strings or numeric Telegram dialog IDs."""
    if isinstance(value, int):
        return value

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
        return stripped

    return value


def first_url(text: str | None) -> str | None:
    if not text:
        return None
    match = URL_RE.search(text)
    return match.group(0).rstrip(").,]}>") if match else None


def message_to_record(message, chat_id: int, channel_name: str) -> dict:
    dt_utc = message.date
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)

    dt_kst = dt_utc.astimezone(KST)
    media_type = type(message.media).__name__ if message.media else None

    return {
        "chat_id": int(chat_id),
        "channel_name": channel_name,
        "telegram_message_id": int(message.id),
        "message_date_utc": dt_utc.astimezone(timezone.utc).isoformat(),
        "message_date_kst": dt_kst.isoformat(),
        "text": message.raw_text or "",
        "sender_id": message.sender_id,
        "is_forwarded": bool(message.fwd_from),
        "reply_to_msg_id": (
            message.reply_to.reply_to_msg_id
            if message.reply_to and hasattr(message.reply_to, "reply_to_msg_id")
            else None
        ),
        "has_media": bool(message.media),
        "media_type": media_type,
        "first_url": first_url(message.raw_text),
    }


async def resolve_channels(client: TelegramClient, configured: list[dict]) -> list[dict]:
    resolved = []

    for item in configured:
        label = item["name"]
        entity_ref = normalize_entity(item["entity"])

        try:
            entity = await client.get_entity(entity_ref)
            chat_id = await client.get_peer_id(entity)
            title = getattr(entity, "title", None) or label
            resolved.append(
                {
                    "name": label or title,
                    "title": title,
                    "entity": entity,
                    "chat_id": chat_id,
                }
            )
            print(f"[OK] {label} -> {title} ({chat_id})")
        except Exception as exc:
            print(f"[ERROR] Could not resolve {label}: {exc}")

    if not resolved:
        raise RuntimeError("No Telegram channels could be resolved.")

    return resolved


async def backfill(client: TelegramClient, channels: list[dict], days: int) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total_inserted = 0

    for ch in channels:
        print(f"\nCollecting last {days} day(s): {ch['title']}")
        inserted = 0
        seen = 0

        async for message in client.iter_messages(ch["entity"]):
            if message.date < since:
                break

            seen += 1
            record = message_to_record(message, ch["chat_id"], ch["name"])

            if save_message(record):
                inserted += 1

        total_inserted += inserted
        print(f"  scanned={seen}, new={inserted}")

    print(f"\nDone. New messages saved: {total_inserted}")


async def live(client: TelegramClient, channels: list[dict]) -> None:
    entity_list = [ch["entity"] for ch in channels]
    channel_by_id = {int(ch["chat_id"]): ch for ch in channels}

    @client.on(events.NewMessage(chats=entity_list))
    async def handler(event):
        message = event.message
        chat_id = int(event.chat_id)

        ch = channel_by_id.get(chat_id)
        if ch is None:
            title = str(chat_id)
            name = str(chat_id)
        else:
            title = ch["title"]
            name = ch["name"]

        record = message_to_record(message, chat_id, name)
        inserted = save_message(record)

        if inserted:
            preview = (message.raw_text or "[media/no text]").replace("\n", " ")[:100]
            local_time = message.date.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{local_time}] {title}: {preview}")

    print("\nLive collector is running. Press Ctrl+C to stop.")
    await client.run_until_disconnected()


async def main_async(args):
    init_db()
    api_id, api_hash, phone = load_settings()
    configured = load_channels()

    session_path = SESSION_DIR / "finance_dashboard"
    client = TelegramClient(str(session_path), api_id, api_hash)

    # First run: Telethon will ask for the Telegram login code in the VS Code terminal.
    if phone:
        await client.start(phone=phone)
    else:
        await client.start()

    try:
        me = await client.get_me()
        print(f"Logged in as: {getattr(me, 'first_name', '')} ({getattr(me, 'id', '')})")

        channels = await resolve_channels(client, configured)

        if args.command == "backfill":
            await backfill(client, channels, args.days)
        elif args.command == "live":
            await live(client, channels)
    finally:
        await client.disconnect()


def parse_args():
    parser = argparse.ArgumentParser(description="Telegram finance collector")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_backfill = subparsers.add_parser("backfill", help="Collect recent history")
    p_backfill.add_argument(
        "--days",
        type=int,
        default=7,
        help="How many days of message history to collect",
    )

    subparsers.add_parser("live", help="Collect new messages continuously")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main_async(parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
