<<<<<<< HEAD
# Telegram Finance Dashboard Starter

A Python-only starter project for:

Telegram channels/groups -> Telethon collector -> SQLite -> Streamlit dashboard

## 1. Create the virtual environment

In VS Code, open this folder, then use the integrated terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Select `.venv/bin/python` as the VS Code Python interpreter.

## 2. Add Telegram credentials

Copy `.env.example` to `.env` and fill in:

```text
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_PHONE=+82...
```

Get your own API ID/API hash from:
https://my.telegram.org -> API development tools

Do not upload `.env` or `.session` files.

## 3. Find Telegram dialog IDs

Run:

```bash
python list_dialogs.py
```

The first run asks for your Telegram login code and, if enabled, your 2FA password.

It also saves `dialogs.csv`.

## 4. Configure channels

Edit `channels.json`.

Public username example:

```json
[
  {
    "name": "FastStockNews",
    "entity": "FastStockNews"
  }
]
```

Private group/channel example: use the numeric `dialog_id` found by `list_dialogs.py`.

## 5. Collect recent history

```bash
python collector.py backfill --days 7
```

Messages are saved to:

```text
data/telegram.db
```

Duplicates are automatically ignored using:
`chat_id + telegram_message_id`.

## 6. Run live collection

```bash
python collector.py live
```

Keep this process running to save newly arriving Telegram messages.

## 7. Open the dashboard

```bash
streamlit run dashboard.py
```

If needed:

```bash
python -m streamlit run dashboard.py
```

## 8. Recreate the old TXT-style output

Example:

```bash
python export_daily.py --date 2026-08-14 --channel FastStockNews
```

Output appears under:

```text
exports/
```

## Recommended development order

1. Verify login.
2. Run `list_dialogs.py`.
3. Add 1 channel to `channels.json`.
4. Backfill 1 day.
5. Inspect dashboard.
6. Add more channels.
7. Run live collection.
8. Only after collection is stable, add ticker/company/theme/event processing.

## Security

- Never publish `.env`.
- Never publish `*.session`.
- Use only chats/channels the logged-in Telegram account is authorized to access.
=======
# finboard
financial dashboard development with Suji
>>>>>>> 714ef2677a0744ae2ac874663d8cae9952efb61b
