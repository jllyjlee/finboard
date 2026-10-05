from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# Resolve relative to this script, even when launched from another directory.
DB_PATH = Path(__file__).resolve().parent / 'data' / 'telegram.db'
AI_FIELDS = (
    'relevant', 'relevance_score', 'category', 'event_type',
    'information_status', 'entities_json', 'needs_review', 'model',
    'processed_at_utc', 'input_tokens', 'cached_input_tokens',
    'output_tokens', 'total_tokens', 'estimated_cost_usd',
)


def read_data(path: Path):
    """Read only: never create or migrate the collector's database."""
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'messages' not in tables:
            raise ValueError('The database has no messages table. Run the collector first.')
        has_ai = 'ai_message_analysis' in tables
        available = {r[1] for r in conn.execute('PRAGMA table_info(ai_message_analysis)')} if has_ai else set()
        fields = ', '.join(
            f'a.{field} AS {field}' if field in available else f'NULL AS {field}'
            for field in AI_FIELDS
        )
        join = 'LEFT JOIN ai_message_analysis a ON a.message_id = m.id' if has_ai else ''
        marker = 'a.message_id' if has_ai else 'NULL'
        df = pd.read_sql_query(
            f'SELECT m.*, {marker} AS analysis_message_id, {fields} FROM messages m {join}', conn
        )
    df['analysed'] = df['analysis_message_id'].notna()
    df['entities'] = df['entities_json'].map(parse_entities)
    df['entity_text'] = df['entities'].map(lambda items: ' '.join(
        str(e.get(k) or '') for e in items
        for k in ('mention', 'normalized_name', 'ticker_candidate', 'exchange')
    ))
    df['score'] = pd.to_numeric(df['relevance_score'], errors='coerce')
    # Collector stores KST timestamps; date filtering uses their local date prefix.
    df['local_date'] = pd.to_datetime(df['message_date_kst'].astype(str).str[:10], errors='coerce').dt.date
    return df, has_ai


def parse_entities(raw):
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else []
        return [e for e in parsed if isinstance(e, dict)] if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def text_value(value, fallback='—'):
    return fallback if value is None or pd.isna(value) or str(value).strip() == '' else str(value)


def safe_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if urlparse(value).scheme in ('http', 'https') else None


def telegram_url(row):
    try:
        chat_id = str(int(row.get('chat_id')))
        message_id = int(row.get('telegram_message_id'))
        if chat_id.startswith('-100') and message_id > 0:
            return f'https://t.me/c/{chat_id[4:]}/{message_id}'
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def order_feed(df, sort):
    if sort == 'Highest relevance':
        return df.sort_values(['score', 'message_date_kst'], ascending=[False, False], na_position='last')
    return df.sort_values('message_date_kst', ascending=sort == 'Oldest first')


def daily_highlights(df, limit=5):
    """Extract source previews, deduplicating repeated text across rooms."""
    ranked = order_feed(df[df['relevant'] == 1], 'Highest relevance')
    seen, highlights = set(), []
    for _, row in ranked.iterrows():
        body = ' '.join(text_value(row.get('text'), '').split())
        fingerprint = body.casefold()
        if not body or fingerprint in seen:
            continue
        seen.add(fingerprint)
        highlights.append((row, body[:240] + ('…' if len(body) > 240 else '')))
        if len(highlights) >= limit:
            break
    return highlights


def render_daily_briefing(data, rooms):
    scope = data[data['channel_name'].isin(rooms)] if rooms else data
    days = sorted(scope['local_date'].dropna().unique(), reverse=True)
    st.subheader('☀️ Daily briefing')
    st.caption('A quick reading view of saved analyses. Highlights are original-text excerpts, not newly generated AI summaries. Room selection applies; other feed filters do not.')
    if not days:
        st.info('No dated messages available for a daily briefing.')
        return
    analysed_days = scope.loc[scope['analysed'], 'local_date'].dropna()
    preferred = max(analysed_days) if not analysed_days.empty else days[0]
    chosen = st.selectbox('Briefing date (KST)', days, index=days.index(preferred), key='briefing_date', format_func=lambda day: day.strftime('%A, %d %B %Y'))
    day = scope[scope['local_date'] == chosen]
    analysed = day[day['analysed']]
    relevant = day[day['relevant'] == 1]
    with st.container(border=True):
        st.markdown(f"**{len(day):,} messages collected · {len(analysed):,} analysed · {len(relevant):,} relevant**")
        pending = len(day) - len(analysed)
        if pending:
            st.info(f'{pending:,} messages for this day have not been analysed. This briefing covers the saved results so far.')
        if analysed.empty:
            st.info('No saved AI analysis for this date. Choose another date or run the processor separately.')
            return
        topics = relevant['category'].dropna().astype(str).value_counts().head(3)
        counts = Counter()
        for items in relevant['entities']:
            counts.update({str(e.get('normalized_name') or e.get('mention')) for e in items if e.get('normalized_name') or e.get('mention')})
        left, right = st.columns(2)
        left.markdown('**Main topics**')
        left.write(' · '.join(f'{name} ({count})' for name, count in topics.items()) or 'No relevant topics saved.')
        right.markdown('**Most-discussed entities**')
        right.write(' · '.join(f'{name} ({count})' for name, count in counts.most_common(5)) or 'No entities saved.')
        st.markdown('**Five highlights to scan**')
        st.caption('Selected by relevance score; identical message text is shown once. Scores do not measure market impact.')
        highlights = daily_highlights(day)
        if not highlights:
            st.write('No relevant text highlights for this date.')
        for number, (row, excerpt) in enumerate(highlights, start=1):
            st.markdown(f"**{number}. {text_value(row['category'], 'Financial update')} · {text_value(row['event_type'])}**")
            st.write(excerpt)
            tags = f"{text_value(row['channel_name'])} · {text_value(row['information_status'])}"
            if row['needs_review'] == 1:
                tags += ' · ⚠ Needs review'
            st.caption(tags)
            with st.expander(f'Read source {number}'):
                st.write(text_value(row.get('text')))
                url = safe_url(row.get('first_url')) or telegram_url(row)
                if url:
                    st.link_button('Open source ↗', url)
        reviews = int((day['needs_review'] == 1).sum())
        if reviews:
            st.caption(f'⚠ {reviews:,} analysed messages flagged for review. Check the review feed before relying on uncertain claims.')


def render_card(row):
    with st.container(border=True):
        st.caption(f"{text_value(row['channel_name'])}  ·  {text_value(row['message_date_kst'])} KST")
        if row['analysed']:
            score = text_value(row['relevance_score'])
            relevance = 'Relevant' if row['relevant'] == 1 else 'Not relevant'
            st.markdown(f'**{relevance} · relevance score {score}**')
            st.caption(' · '.join(text_value(row[k]) for k in ('category', 'event_type', 'information_status')))
            if row['needs_review'] == 1:
                st.warning('AI flagged this message for review.')
            labels = []
            for entity in row['entities']:
                name = entity.get('normalized_name') or entity.get('mention') or 'Unknown entity'
                ticker = entity.get('ticker_candidate')
                labels.append(f'{name} ({ticker})' if ticker else str(name))
            if labels:
                st.write('Entities: ' + ' · '.join(dict.fromkeys(labels)))
        else:
            st.caption('Awaiting AI analysis')
        body = text_value(row.get('text'), '[Media message without text]')
        st.write(body[:500] + ('…' if len(body) > 500 else ''))
        if len(body) > 500:
            with st.expander('Read full original message'):
                st.write(body)
        article, telegram = safe_url(row.get('first_url')), telegram_url(row)
        links = st.columns(2)
        if article:
            links[0].link_button('Open linked source ↗', article)
        if telegram:
            links[1].link_button('Open in Telegram ↗', telegram)
        with st.expander('Analysis details'):
            if row['analysed']:
                st.caption(f"Model: {text_value(row['model'])} · Processed (UTC): {text_value(row['processed_at_utc'])}")
                st.json(row['entities'])
            else:
                st.write('Run process_messages.py separately to analyse this message.')
            flags = [label for key, label in [('is_forwarded', 'Forwarded'), ('has_media', 'Media attached')] if row.get(key) == 1]
            if flags:
                st.caption(' · '.join(flags))


def main():
    st.set_page_config(page_title='Finboard', page_icon='📡', layout='wide')
    st.markdown('''<style>
    .block-container {padding-top: 2rem; max-width: 1450px;}
    [data-testid="stMetric"] {background: var(--secondary-background-color); padding: 16px; border-radius: 12px;}
    </style>''', unsafe_allow_html=True)
    heading, refresh = st.columns([6, 1])
    heading.title('📡 Finboard')
    heading.caption('Financial intelligence from your Telegram rooms · KST')
    refresh.button('↻ Refresh', help='Reload saved messages; no AI requests are made.')
    if not DB_PATH.exists():
        st.info(f'No database found at {DB_PATH}. Place this file in your project root and run collector.py first.')
        return
    try:
        data, has_ai = read_data(DB_PATH)
    except (sqlite3.Error, ValueError, KeyError) as exc:
        st.error(f'Could not load messages: {exc}')
        return
    if data.empty:
        st.info('No collected messages yet. Run collector.py first.')
        return
    if not has_ai:
        st.info('AI analysis is not saved yet. The original feed is available below.')

    valid_dates = data['local_date'].dropna()
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    earliest = min(valid_dates) if not valid_dates.empty else today
    latest = max(valid_dates) if not valid_dates.empty else today
    # Include saved analyses on first launch even if they are older than a week.
    with st.sidebar:
        st.header('Your feed')
        st.caption('Reads saved data only · no API cost')
        mode = st.radio('Messages', ['Analysed', 'Relevant', 'Needs review', 'All', 'Unanalysed'], index=0 if data['analysed'].any() else 3)
        rooms = st.multiselect('Rooms', sorted(data['channel_name'].dropna().unique()))
        dates = st.date_input('Date range (KST)', value=(earliest, latest))
        keyword = st.text_input('Search messages & entities', placeholder='HBM, 삼성전자, NVDA…')
        categories = st.multiselect('Categories', sorted(data['category'].dropna().astype(str).unique()))
        statuses = st.multiselect('Information status', sorted(data['information_status'].dropna().astype(str).unique()))
        sort = st.selectbox('Sort by', ['Newest first', 'Highest relevance', 'Oldest first'])
        per_page = st.selectbox('Messages per page', [10, 20, 50], index=1)

    df = data.copy()
    if mode == 'Analysed':
        df = df[df['analysed']]
    elif mode == 'Relevant':
        df = df[df['relevant'] == 1]
    elif mode == 'Needs review':
        df = df[df['needs_review'] == 1]
    elif mode == 'Unanalysed':
        df = df[~df['analysed']]
    if rooms:
        df = df[df['channel_name'].isin(rooms)]
    if isinstance(dates, (tuple, list)) and len(dates) == 2:
        df = df[df['local_date'].between(dates[0], dates[1])]
    else:
        st.info('Select both a start and an end date to apply the date filter.')
    if categories:
        df = df[df['category'].isin(categories)]
    if statuses:
        df = df[df['information_status'].isin(statuses)]
    if keyword.strip():
        search = df['text'].fillna('') + ' ' + df['entity_text']
        df = df[search.str.contains(keyword.strip(), case=False, regex=False)]
    df = order_feed(df, sort)

    render_daily_briefing(data, rooms)
    st.divider()
    metrics = st.columns(4)
    metrics[0].metric('Matching messages', f'{len(df):,}')
    metrics[1].metric('Relevant', f"{int((df['relevant'] == 1).sum()):,}")
    metrics[2].metric('Needs review', f"{int((df['needs_review'] == 1).sum()):,}")
    metrics[3].metric('Rooms', f"{df['channel_name'].nunique():,}")
    analysed_count = int(data['analysed'].sum())
    st.caption(f"Database total: {len(data):,} messages · {analysed_count:,} analysed · {len(data) - analysed_count:,} awaiting analysis")
    st.progress(analysed_count / len(data))
    feed, priority, entities, table, usage = st.tabs(['Message feed', 'Priority feed', 'Entities', 'Data & export', 'AI usage'])
    with feed:
        if df.empty:
            st.info('No matching messages. Try All, a wider date range, or fewer filters.')
        else:
            signature = repr((mode, rooms, dates, keyword, categories, statuses, sort, per_page))
            if st.session_state.get('filter_signature') != signature:
                st.session_state['feed_page'] = 1
                st.session_state['filter_signature'] = signature
            pages = max(1, (len(df) + per_page - 1) // per_page)
            st.session_state['feed_page'] = min(st.session_state.get('feed_page', 1), pages)
            page = st.number_input('Page', min_value=1, max_value=pages, step=1, key='feed_page')
            start = (page - 1) * per_page
            st.caption(f'{start + 1}–{min(start + per_page, len(df))} of {len(df):,} · {pages} pages')
            for _, row in df.iloc[start:start + per_page].iterrows():
                render_card(row)
    with priority:
        st.caption('Relevant messages ranked by saved relevance score. This score measures relevance, not investment quality or event importance. Sidebar filters apply.')
        selected = order_feed(df[df['relevant'] == 1], 'Highest relevance').head(10)
        if selected.empty:
            st.info('No relevant analysed messages match these filters.')
        for _, row in selected.iterrows():
            render_card(row)
    with entities:
        st.caption('Mentions across matching messages. Tickers are AI candidates; this is not a stock recommendation list.')
        counts = Counter()
        for items in df['entities']:
            seen = set()
            for e in items:
                name = e.get('normalized_name') or e.get('mention')
                if name:
                    seen.add((str(name), str(e.get('ticker_candidate') or ''), str(e.get('exchange') or ''), str(e.get('entity_type') or '')))
            counts.update(seen)
        rows = [{'Entity': k[0], 'Ticker candidate': k[1], 'Exchange': k[2], 'Type': k[3], 'Messages': n} for k, n in counts.most_common()]
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info('No saved entities match these filters.')
    with table:
        columns = ['message_date_kst', 'channel_name', 'analysed', 'relevant', 'relevance_score', 'category', 'event_type', 'information_status', 'needs_review', 'entity_text', 'text', 'first_url']
        export = df[[c for c in columns if c in df.columns]]
        st.dataframe(export, use_container_width=True, hide_index=True)
        st.download_button('Download filtered CSV', export.to_csv(index=False).encode('utf-8-sig'), 'finboard_messages.csv', 'text/csv')
    with usage:
        st.caption('Recorded usage across the whole database. Stored cost estimates are produced by process_messages.py; opening this dashboard makes no AI requests.')
        cols = st.columns(3)
        tokens = pd.to_numeric(data['total_tokens'], errors='coerce').sum()
        cost = pd.to_numeric(data['estimated_cost_usd'], errors='coerce').sum()
        cols[0].metric('Recorded tokens', f'{int(tokens):,}')
        cols[1].metric('Recorded estimated cost', f'${cost:.4f}')
        cols[2].metric('Analysed messages', f'{analysed_count:,}')
        if data['analysed'].any():
            st.dataframe(data.loc[data['analysed'], ['model', 'processed_at_utc', 'input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens', 'estimated_cost_usd']], use_container_width=True, hide_index=True)
    st.caption('AI output may contain errors. Review the original source, especially flagged messages. Summaries and translation are not yet stored by your processor.')


if __name__ == '__main__':
    main()
