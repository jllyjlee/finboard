from __future__ import annotations

import argparse

from calendar_feed import sync_calendar


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import upcoming events from a configured public ICS calendar."
    )
    parser.add_argument(
        "--days",
        type=int,
        required=True,
        help="Look ahead N days (required).",
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be a positive integer.")
    return args


def main():
    args = parse_args()
    saved = sync_calendar(args.days)
    print(f"Saved {saved:,} upcoming calendar event(s) from the next {args.days} day(s).")


if __name__ == "__main__":
    main()
