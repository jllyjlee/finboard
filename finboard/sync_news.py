from __future__ import annotations

import argparse

from news_feeds import sync_news


def parse_args():
    parser = argparse.ArgumentParser(
        description="Save public Google News RSS stories for the selected recent date window."
    )
    parser.add_argument(
        "--days",
        type=int,
        required=True,
        help="Only save stories from the last N days (required).",
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be a positive integer.")
    return args


def main():
    args = parse_args()
    inserted, failures = sync_news(args.days)
    print(f"Saved {inserted:,} new article(s) from the last {args.days} day(s).")
    if failures:
        print(f"{len(failures)} feed(s) failed:")
        for failure in failures:
            print(f"  - {failure}")


if __name__ == "__main__":
    main()
