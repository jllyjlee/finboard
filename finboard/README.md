# Finboard

Finboard combines Telegram posts, public news RSS, a configurable public event calendar, and market prices in a bilingual Streamlit dashboard.

## Setup

From the `finboard` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` in this directory and fill in the integrations you plan to use:

```text
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_PHONE=+82...
OPENAI_API_KEY=...
FINBOARD_CALENDAR_ICS_URL=https://your-calendar-provider.example/calendar.ics
```

Telegram credentials are needed only by the collector. `OPENAI_API_KEY` is needed only by the AI processing scripts. The calendar URL must be a public ICS feed. Keep `.env` and Telegram `.session` files private.

For your Telegram login, get the API ID and API hash from [my.telegram.org](https://my.telegram.org) under **API development tools**, then put those values and your phone number in `.env`. The collector uses a separate `finboard_personal` session so it does not reuse the existing `finance_dashboard` login. On its first run, enter the Telegram login code (and your two-step verification password, if enabled) in the terminal. Do not share or commit your credentials or session file.

## Collect and import data

Telegram collection continues to use the existing commands:

```bash
python collector.py backfill --days 7
python collector.py live
```

Fetch categorized English and Korean Google News RSS items without using AI tokens:

```bash
python sync_news.py --days <N>
```

Import upcoming events from the configured public ICS calendar:

```bash
python sync_calendar.py --days <N>
```

Both commands require an explicit date window. News fields include business and finance, economy, politics, healthcare and medicine, AI and technology, science, sports, geopolitics, energy and commodities, and crypto. Google News RSS links may redirect through Google before opening the publisher's article.

## Generate bilingual summaries and event links

AI work is never triggered by opening or refreshing the dashboard. These commands make OpenAI requests, so choose the date window and item limit deliberately:

```bash
python process_messages.py --days <N> --limit <N>
python process_news.py --days <N> --limit <N>
```

Both `--days` and `--limit` are required for each AI command so the cost-impacting batch size is explicit. Each processed story gets a news-field classification, relevance assessment, Korean and English summaries, possible ticker candidates, and an event date only when the source states one explicitly. Output includes token counts and an estimated cost using the configured pricing assumptions. Estimates may differ from actual billing.

## Run the dashboard

```bash
python -m streamlit run dashboard.py
```

The dashboard provides:

- Date, source, and news-field filters.
- Korean and English daily briefing tabs with original-source links. Telegram posts appear first as the primary briefing, with a direct post link and separately linked reports/advisories shared in the post (including multiple and hidden text links). Public news appears afterward as supporting coverage and is not automatically cross-checked against Telegram reports. The collector stores every shared link on new collection runs; older saved posts use links recoverable from their text and the previously stored first URL.
- An agenda combining configured calendar entries with explicitly dated events extracted from saved stories. Story-derived dates are not guessed; the calendar feed is only as complete and current as its provider.
- Related ticker candidates and a square-style watchlist of Korean and U.S. shares/ETFs, priced from Yahoo Finance public data. Quotes are latest available daily closes, not real-time prices, and may be delayed or unavailable.
- Generic capital-preservation, balanced, and growth-oriented portfolio examples. These are educational illustrations, not personalized investment advice or guaranteed outcomes.
- Searchable stories, entities, filtered data export, and AI usage totals.

An AI ticker mapping is not a verified listing, and news relevance is not a measure of future performance. Verify the original source and all prices before acting.

## Other tools

```bash
python list_dialogs.py
python export_daily.py --date YYYY-MM-DD --channel ALL
python -m pytest -q
```
