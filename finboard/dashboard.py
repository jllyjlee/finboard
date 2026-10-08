from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from market_data import WATCHLIST, Asset, asset_for_entity, fetch_quotes
from portfolio import PORTFOLIO_EXAMPLES, allocation_total

# Resolve relative to this script, even when launched from another directory.
DB_PATH = Path(__file__).resolve().parent / 'data' / 'telegram.db'
AI_FIELDS = (
    'relevant', 'relevance_score', 'category', 'event_type',
    'news_field', 'information_status', 'entities_json', 'needs_review',
    'summary_ko', 'summary_en', 'event_date_kst', 'model',
    'processed_at_utc', 'input_tokens', 'cached_input_tokens',
    'output_tokens', 'total_tokens', 'estimated_cost_usd',
)
NEWS_FIELD_LABELS = {
    'business_finance': 'Business & Finance',
    'economy': 'Economy',
    'politics': 'Politics',
    'healthcare': 'Healthcare & Medicine',
    'ai_technology': 'AI & Technology',
    'science': 'Science',
    'sports': 'Sports',
    'geopolitics': 'Geopolitics',
    'energy_commodities': 'Energy & Commodities',
    'crypto': 'Crypto',
    'other': 'Other',
}


def read_data(path: Path):
    """Read only: never create or migrate the collector's database."""
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'messages', 'external_articles', 'calendar_events'}.intersection(tables):
            raise ValueError('The database has no Telegram messages, RSS stories, or calendar events.')
        has_ai = 'ai_message_analysis' in tables
        if 'messages' in tables:
            available = (
                {r[1] for r in conn.execute('PRAGMA table_info(ai_message_analysis)')}
                if has_ai else set()
            )
            fields = ', '.join(
                f'a.{field} AS {field}' if field in available else f'NULL AS {field}'
                for field in AI_FIELDS
            )
            join = 'LEFT JOIN ai_message_analysis a ON a.message_id = m.id' if has_ai else ''
            marker = 'a.message_id' if has_ai else 'NULL'
            messages = pd.read_sql_query(
                f'SELECT m.*, {marker} AS analysis_item_id, {fields} FROM messages m {join}', conn
            )
        else:
            messages = pd.DataFrame(
                columns=[
                    'channel_name', 'first_url', 'message_date_kst', 'text',
                    'analysis_item_id', *AI_FIELDS,
                ]
            )
        messages['source_type'] = 'Telegram'
        messages['source_name'] = messages['channel_name']
        messages['source_link'] = messages['first_url']
        messages['article_title'] = ''
        messages['source_language'] = 'ko'
        messages['published_at'] = messages['message_date_kst']
        messages['requires_ai'] = True

        articles = pd.DataFrame()
        calendar_items = pd.DataFrame()
        if 'external_articles' in tables:
            article_analysis = 'external_article_analysis' in tables
            analysis_columns = (
                {r[1] for r in conn.execute('PRAGMA table_info(external_article_analysis)')}
                if article_analysis else set()
            )
            analysis_fields = ', '.join(
                f'analysis.{field} AS {field}' if field in analysis_columns else f'NULL AS {field}'
                for field in AI_FIELDS
                if field != 'news_field'
            )
            analyzed_news_field = (
                'analysis.news_field AS analyzed_news_field'
                if 'news_field' in analysis_columns else 'NULL AS analyzed_news_field'
            )
            article_join = (
                'LEFT JOIN external_article_analysis analysis ON analysis.article_id = article.id'
                if article_analysis else ''
            )
            article_marker = 'analysis.article_id' if article_analysis else 'NULL'
            articles = pd.read_sql_query(
                f'''
                SELECT article.*, {article_marker} AS analysis_item_id,
                       {analysis_fields}, {analyzed_news_field}
                FROM external_articles article {article_join}
                ''',
                conn,
            )

            articles['requires_ai'] = True

        if 'calendar_events' in tables:
            calendar_items = pd.read_sql_query(
                """
                SELECT id, title, description, start_at_utc, event_url, source
                FROM calendar_events
                """,
                conn,
            )

    if not articles.empty:
        articles['source_type'] = 'News'
        articles['source_name'] = articles['source'].fillna('News source')
        articles['source_link'] = articles['url']
        articles['article_title'] = articles['title']
        articles['channel_name'] = articles['source_name']
        articles['first_url'] = articles['url']
        articles['chat_id'] = None
        articles['telegram_message_id'] = None
        articles['text'] = articles.apply(
            lambda row: '\n\n'.join(
                str(value).strip() for value in (row.get('title'), row.get('description'))
                if isinstance(value, str) and value.strip()
            ),
            axis=1,
        )
        articles['message_date_kst'] = pd.to_datetime(
            articles['published_at_utc'], errors='coerce', utc=True
        ).dt.tz_convert('Asia/Seoul').dt.strftime('%Y-%m-%d %H:%M:%S')
        articles['source_language'] = articles['source_language'].fillna('')
        articles['news_field'] = articles['analyzed_news_field'].fillna(articles['news_field'])
    if not calendar_items.empty:
        calendar_items['source_type'] = 'Calendar'
        calendar_items['source_name'] = calendar_items['source'].fillna('Public calendar')
        calendar_items['channel_name'] = calendar_items['source_name']
        calendar_items['source_link'] = calendar_items['event_url']
        calendar_items['first_url'] = calendar_items['event_url']
        calendar_items['article_title'] = calendar_items['title']
        calendar_items['source_language'] = 'en'
        calendar_items['news_field'] = 'economy'
        calendar_items['analysis_item_id'] = None
        calendar_items['relevant'] = 1
        calendar_items['relevance_score'] = None
        calendar_items['needs_review'] = 0
        calendar_items['summary_ko'] = None
        calendar_items['summary_en'] = None
        calendar_items['entities_json'] = '[]'
        calendar_items['chat_id'] = None
        calendar_items['telegram_message_id'] = None
        calendar_items['text'] = calendar_items.apply(
            lambda row: '\n\n'.join(
                str(value).strip() for value in (row.get('title'), row.get('description'))
                if isinstance(value, str) and value.strip()
            ),
            axis=1,
        )
        local_starts = pd.to_datetime(
            calendar_items['start_at_utc'], errors='coerce', utc=True
        ).dt.tz_convert('Asia/Seoul')
        calendar_items['message_date_kst'] = local_starts.dt.strftime('%Y-%m-%d %H:%M:%S')
        calendar_items['event_date_kst'] = local_starts.dt.strftime('%Y-%m-%d')
        calendar_items['published_at'] = calendar_items['message_date_kst']
        calendar_items['requires_ai'] = False
    df = pd.concat([messages, articles, calendar_items], ignore_index=True, sort=False)

    df['analysed'] = df['analysis_item_id'].notna()
    if 'source_type' not in df:
        df['source_type'] = 'Telegram'
    if 'source_name' not in df:
        df['source_name'] = df['channel_name']
    if 'source_link' not in df:
        df['source_link'] = df['first_url']
    if 'article_title' not in df:
        df['article_title'] = ''
    if 'source_language' not in df:
        df['source_language'] = 'ko'
    if 'requires_ai' not in df:
        df['requires_ai'] = True
    if 'published_at' not in df:
        df['published_at'] = df['message_date_kst']
    if 'news_field' not in df:
        df['news_field'] = None
    df['news_field'] = df['news_field'].fillna('other')
    df['entities'] = df['entities_json'].map(parse_entities)
    df['entity_text'] = df['entities'].map(lambda items: ' '.join(
        str(e.get(k) or '') for e in items
        for k in ('mention', 'normalized_name', 'ticker_candidate', 'exchange')
    ))
    df['score'] = pd.to_numeric(df['relevance_score'], errors='coerce')
    # Collector timestamps are KST; RSS timestamps are converted to KST above.
    df['local_date'] = pd.to_datetime(
        df['message_date_kst'].astype(str).str[:10], errors='coerce'
    ).dt.date
    return df, bool(df['analysed'].any())


def parse_entities(raw):
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else []
        return [e for e in parsed if isinstance(e, dict)] if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def text_value(value, fallback='—'):
    return fallback if value is None or pd.isna(value) or str(value).strip() == '' else str(value)


def format_label(value, fallback='—'):
    """Make stored AI labels readable without changing their saved values."""
    label = text_value(value, fallback).replace('_', ' ').strip()
    return label.title() if label != fallback else fallback


def safe_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if urlparse(value).scheme in ('http', 'https') else None


def telegram_report_urls(row):
    links = []
    stored_urls = row.get('shared_urls_json')
    if isinstance(stored_urls, str) and stored_urls.strip():
        try:
            parsed = json.loads(stored_urls)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            links.extend(parsed)

    text = row.get('text')
    if isinstance(text, str):
        links.extend(match.group(0).rstrip(').,]}>;') for match in re.finditer(r'https?://\S+', text))
    links.append(row.get('first_url'))
    return list(dict.fromkeys(url for item in links if (url := safe_url(item))))


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


def briefing_source_groups(day):
    return [
        (source_type, day[day['source_type'] == source_type])
        for source_type in ('Telegram', 'News', 'Calendar')
        if (day['source_type'] == source_type).any()
    ]


def render_daily_briefing(scope):
    days = sorted(scope['local_date'].dropna().unique(), reverse=True)
    st.subheader('Daily briefing · 주요 소식')
    st.caption('Telegram posts are the primary briefing. Public news is shown afterward as supporting coverage, not as automated verification of Telegram reports. AI summaries are generated only by the bounded processing commands; relevance scores do not measure market impact.')
    if not days:
        st.info('No dated stories match the selected filters.')
        return
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    past_days = [day for day in days if day <= today]
    preferred_day = past_days[0] if past_days else days[0]
    chosen = st.selectbox(
        'Briefing date · KST',
        days,
        index=days.index(preferred_day),
        key='briefing_date',
        format_func=lambda day: day.strftime('%A, %d %B %Y'),
    )
    day = scope[scope['local_date'] == chosen].copy()
    day['sort_score'] = pd.to_numeric(day['relevance_score'], errors='coerce').fillna(0)
    day = day.sort_values(['sort_score', 'published_at'], ascending=[False, False])
    total, relevant_count, review_count, waiting_count = st.columns(4)
    total.metric('Stories', f'{len(day):,}')
    relevant_count.metric('Market-relevant', f"{int((day['relevant'] == 1).sum()):,}")
    review_count.metric('Needs review', f"{int((day['needs_review'] == 1).sum()):,}")
    waiting_count.metric(
        'Awaiting AI summary',
        f"{int((day['requires_ai'] & ~day['analysed']).sum()):,}",
    )
    if day.empty:
        return

    language_tabs = st.tabs(['한국어', 'English'])
    for tab, language, summary_column in (
        (language_tabs[0], 'ko', 'summary_ko'),
        (language_tabs[1], 'en', 'summary_en'),
    ):
        with tab:
            for source_type, group in briefing_source_groups(day):
                if source_type == 'Telegram':
                    heading = '텔레그램 원문 우선' if language == 'ko' else 'Telegram posts · primary'
                elif source_type == 'News':
                    heading = (
                        '외부 뉴스 참고 · 자동 교차검증 아님'
                        if language == 'ko'
                        else 'External news · supporting coverage, not automatic verification'
                    )
                else:
                    heading = '일정 안내' if language == 'ko' else 'Calendar notices'
                st.markdown(f'#### {heading}')
                shown = 0
                for _, row in group.iterrows():
                    if (
                        pd.notna(row['relevant'])
                        and row['relevant'] != 1
                        and source_type != 'News'
                    ):
                        continue
                    summary = text_value(row.get(summary_column), '')
                    if not summary:
                        source_language = str(row.get('source_language') or '').lower()
                        if source_language == language:
                            summary = text_value(row.get('article_title') or row.get('text'), '')
                        else:
                            continue
                    with st.container(border=True):
                        if row.get('news_field'):
                            st.caption(
                                f"{NEWS_FIELD_LABELS.get(str(row['news_field']), format_label(row['news_field']))}"
                                f" · {text_value(row.get('source_name'))}"
                            )
                        st.markdown(summary)
                        if row['needs_review'] == 1:
                            st.caption(
                                '검토 필요 · 원문 확인 필요'
                                if language == 'ko'
                                else 'Needs review · verify the original source'
                            )
                        if source_type == 'Telegram':
                            post_url = telegram_url(row)
                            if post_url:
                                st.link_button(
                                    '텔레그램 게시물 ↗' if language == 'ko' else 'Open Telegram post ↗',
                                    post_url,
                                )
                            for index, report_url in enumerate(telegram_report_urls(row), start=1):
                                label = (
                                    '텔레그램 공유 보고서 / 권고문 ↗'
                                    if language == 'ko'
                                    else 'Open Telegram-linked report / advisory ↗'
                                )
                                if index > 1:
                                    label += f' ({index})'
                                st.link_button(label, report_url)
                        else:
                            source_url = safe_url(row.get('source_link')) or telegram_url(row)
                            if source_url:
                                st.link_button('원문 / Original source ↗', source_url)
                    shown += 1
                    if shown >= 12:
                        break
                if shown == 0:
                    st.info(
                        '표시할 내용이 아직 없습니다.'
                        if language == 'ko'
                        else 'No items are available in this section yet.'
                    )


def upcoming_agenda(data):
    st.subheader('Current & upcoming agenda · 주요 일정')
    dates = pd.to_datetime(data['event_date_kst'], errors='coerce').dt.normalize()
    today = pd.Timestamp(datetime.now(ZoneInfo('Asia/Seoul')).date())
    upcoming = dates.notna() & (dates >= today)
    agenda = data.loc[upcoming].copy()
    agenda['agenda_date'] = dates[upcoming]
    has_event_source = agenda['source_type'].isin(['News', 'Calendar'])
    agenda = agenda[has_event_source | (agenda['relevant'] == 1)]
    agenda = agenda.sort_values(['agenda_date', 'score'], ascending=[True, False])
    if agenda.empty:
        st.info('No explicit current or upcoming dates have been extracted. Dates are never inferred from article publication time.')
        return
    for _, row in agenda.head(12).iterrows():
        event_text = text_value(row.get('summary_en'), '')
        if not event_text:
            event_text = text_value(row.get('article_title'), '')
        if not event_text:
            event_text = text_value(row.get('text'), '')
        if not event_text:
            continue
        left, right = st.columns([5, 1])
        left.markdown(f"**{row['agenda_date'].strftime('%d %b %Y')} · {NEWS_FIELD_LABELS.get(str(row.get('news_field')), 'Event')}**")
        left.caption(event_text)
        source_url = safe_url(row.get('source_link')) or telegram_url(row)
        if source_url:
            right.link_button('Source ↗', source_url)


def event_entities(data):
    entities = []
    for _, row in data.iterrows():
        if row.get('relevant') != 1:
            continue
        for entity in row.get('entities', []):
            if (
                entity.get('ticker_candidate')
                and entity.get('entity_type') in {'company', 'security'}
            ):
                entities.append(entity)
    unique = {}
    for entity in entities:
        key = (str(entity.get('ticker_candidate')).upper(), str(entity.get('exchange') or '').upper())
        unique.setdefault(key, entity)
    return list(unique.values())


@st.cache_data(ttl=900, show_spinner=False)
def cached_quotes(assets: tuple[Asset, ...]):
    return fetch_quotes(assets)


def quote_text(quote):
    price = quote.get('price')
    if price is None:
        return 'Price unavailable'
    asset = quote['asset']
    decimals = 0 if asset.currency == 'KRW' else 2
    return f"{price:,.{decimals}f} {asset.currency}"


def render_market_board(quotes_by_symbol):
    st.subheader('Market snapshot · 주요 종목')
    st.caption('Latest available daily close, not a real-time quote. Prices come from Yahoo Finance public data; currency is shown per card.')
    for start in range(0, len(WATCHLIST), 5):
        cards = st.columns(5)
        for card, asset in zip(cards, WATCHLIST[start:start + 5]):
            with card.container(border=True):
                st.caption(f'{asset.market} · {asset.symbol}')
                st.markdown(f'**{asset.name}**')
                quote = quotes_by_symbol.get(asset.yahoo_symbol)
                if quote is None:
                    st.caption('Price unavailable')
                    continue
                delta = quote.get('change_pct')
                st.metric(
                    'Last close',
                    quote_text(quote),
                    delta=f'{delta:+.2f}%' if delta is not None else None,
                )
                st.caption(f"Close date · {text_value(quote.get('as_of'))}")


def render_event_stocks(entities, quotes_by_symbol):
    st.subheader('Stocks mentioned in relevant events · 관련 종목')
    st.caption('Ticker mappings are AI candidates, not verified listings or investment recommendations.')
    if not entities:
        st.info('No ticker candidates were saved for relevant stories in this date range.')
        return
    cards = st.columns(min(4, len(entities)))
    for index, entity in enumerate(entities):
        asset = asset_for_entity(entity)
        with cards[index % len(cards)].container(border=True):
            label = entity.get('normalized_name') or entity.get('mention') or 'Unmapped entity'
            st.caption(f"{entity.get('exchange') or 'Exchange unknown'} · {entity.get('ticker_candidate')}")
            st.markdown(f'**{label}**')
            if entity.get('ticker_confidence') is not None:
                st.caption(f"Ticker mapping confidence · {entity['ticker_confidence']}%")
            if asset and asset.yahoo_symbol in quotes_by_symbol:
                quote = quotes_by_symbol[asset.yahoo_symbol]
                delta = quote.get('change_pct')
                st.metric(
                    'Last close',
                    quote_text(quote),
                    delta=f'{delta:+.2f}%' if delta is not None else None,
                )
                st.caption(f"Last close · {text_value(quote.get('as_of'))}")
            else:
                st.caption('No quote available for this ticker.')


def render_portfolio_examples(entities):
    st.subheader('Illustrative portfolio mixes · 참고용 포트폴리오')
    st.caption('Generic educational examples only—not personalized advice, a forecast, or a recommendation to buy. Capital and cash-equivalent products are not guaranteed unless a specific product and applicable protections say so.')
    tabs = st.tabs([profile['name'] for profile in PORTFOLIO_EXAMPLES])
    for tab, profile in zip(tabs, PORTFOLIO_EXAMPLES):
        with tab:
            st.write(profile['description'])
            for category, weight in profile['allocation']:
                st.markdown(f'**{category} · {weight}%**')
                st.progress(weight / 100)
            if allocation_total(profile) != 100:
                st.error('Portfolio allocation totals must equal 100%.')
                continue
            event_weight = next(
                weight for category, weight in profile['allocation']
                if category == 'Event-linked research sleeve'
            )
            linked = [
                str(entity.get('normalized_name') or entity.get('mention') or entity.get('ticker_candidate'))
                for entity in entities
            ]
            st.caption(
                f"The {event_weight}% event-linked sleeve is a hypothetical research allocation, "
                "not an automatic trade. Relevant names from the selected news window:"
            )
            st.write(' · '.join(dict.fromkeys(linked[:8])) or 'No verified ticker candidates in this window.')

def render_card(row):
    with st.container(border=True):
        st.caption(f"{text_value(row['channel_name'])}  ·  {text_value(row['message_date_kst'])} KST")
        if row['analysed']:
            score = text_value(row['relevance_score'])
            relevance = 'Relevant' if row['relevant'] == 1 else 'Not relevant'
            st.markdown(f'**{relevance} · relevance {score} / 100**')
            st.caption(' · '.join(format_label(row[k]) for k in ('category', 'event_type', 'information_status')))
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
        st.text(body[:500] + ('…' if len(body) > 500 else ''))
        if len(body) > 500:
            with st.expander('Read full original message'):
                st.text(body)
        telegram = telegram_url(row)
        report_urls = telegram_report_urls(row)
        if telegram:
            st.link_button('Open Telegram post ↗', telegram)
        for index, report_url in enumerate(report_urls, start=1):
            label = 'Open Telegram-linked report / advisory ↗'
            if index > 1:
                label += f' ({index})'
            st.link_button(label, report_url)
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
    .block-container {padding-top: 1.5rem; max-width: 1380px;}
    [data-testid="stMetric"] {background: var(--secondary-background-color); padding: 14px 16px; border-radius: 12px; border: 1px solid rgba(128, 128, 128, 0.18);}
    [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] {border-color: rgba(128, 128, 128, 0.22);}
    </style>''', unsafe_allow_html=True)
    heading, refresh = st.columns([6, 1])
    heading.title('📡 Finboard')
    heading.caption('Bilingual news, upcoming events, and market prices · Korea Standard Time')
    if refresh.button('↻ Refresh', help='Reload saved data and market prices; no AI requests are made.'):
        cached_quotes.clear()
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
        st.info('AI summaries are not saved yet. Run a date-bounded processing command when you are ready to spend tokens.')

    valid_dates = data['local_date'].dropna()
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    earliest = min(valid_dates) if not valid_dates.empty else today
    latest = max(valid_dates) if not valid_dates.empty else today
    fields_available = sorted(data['news_field'].dropna().astype(str).unique())
    source_types_available = sorted(data['source_type'].dropna().astype(str).unique())
    with st.sidebar:
        st.header('Brief filters')
        st.caption('Filters apply to briefs, agendas, and story lists. Opening this page makes no AI requests.')
        mode = st.radio('Show', ['All', 'Relevant', 'Needs review', 'Analysed', 'Unanalysed'], index=0)
        rooms = st.multiselect('Rooms / sources', sorted(data['channel_name'].dropna().unique()))
        dates = st.date_input('Date range · KST', value=(earliest, latest))
        fields = st.multiselect(
            'News fields',
            fields_available,
            format_func=lambda value: NEWS_FIELD_LABELS.get(value, format_label(value)),
        )
        source_types = st.multiselect(
            'Sources',
            source_types_available,
            default=source_types_available,
        )
        keyword = st.text_input('Search stories & entities', placeholder='HBM, 삼성전자, NVDA…')

    df = data.copy()
    if mode == 'Relevant':
        df = df[df['relevant'] == 1]
    elif mode == 'Needs review':
        df = df[df['needs_review'] == 1]
    elif mode == 'Analysed':
        df = df[df['analysed']]
    elif mode == 'Unanalysed':
        df = df[~df['analysed']]
    if rooms:
        df = df[df['channel_name'].isin(rooms)]
    if source_types:
        df = df[df['source_type'].isin(source_types)]
    if isinstance(dates, (tuple, list)) and len(dates) == 2:
        df = df[df['local_date'].between(dates[0], dates[1])]
    else:
        st.info('Select both a start and an end date to apply the date filter.')
    if fields:
        df = df[df['news_field'].isin(fields)]
    if keyword.strip():
        search = (
            df['text'].fillna('')
            + ' ' + df['entity_text']
            + ' ' + df['summary_ko'].fillna('')
            + ' ' + df['summary_en'].fillna('')
        )
        df = df[search.str.contains(keyword.strip(), case=False, regex=False)]
    df = order_feed(df, 'Newest first')

    render_daily_briefing(df)
    chosen_date = st.session_state.get('briefing_date')
    selected_day = df[df['local_date'] == chosen_date] if chosen_date else df
    st.divider()
    upcoming_agenda(df)
    linked_entities = event_entities(selected_day)
    dynamic_assets = tuple(
        asset for entity in linked_entities
        if (asset := asset_for_entity(entity)) is not None
    )
    assets_by_symbol = {asset.yahoo_symbol: asset for asset in (*WATCHLIST, *dynamic_assets)}
    quotes_by_symbol = {}
    if os.getenv('FINBOARD_SKIP_QUOTES') == '1':
        st.info('Stock quote fetching is disabled for this run (FINBOARD_SKIP_QUOTES=1).')
    else:
        try:
            quotes = cached_quotes(tuple(assets_by_symbol.values()))
            quotes_by_symbol = {
                quote['asset'].yahoo_symbol: quote
                for quote in quotes
            }
        except (OSError, RuntimeError, ValueError) as exc:
            st.error(f'Could not load market prices: {exc}')
    render_event_stocks(linked_entities, quotes_by_symbol)
    render_market_board(quotes_by_symbol)
    render_portfolio_examples(linked_entities)
    st.divider()
    analysed_count = int(data['analysed'].sum())
    feed, priority, entities, table, usage = st.tabs(
        ['Stories', 'Priority', 'Entities', 'Data & export', 'AI usage']
    )
    with feed:
        st.subheader('Stories in selected date range')
        metrics = st.columns(4)
        metrics[0].metric('Matching messages', f'{len(df):,}')
        metrics[1].metric('Relevant', f"{int((df['relevant'] == 1).sum()):,}")
        metrics[2].metric('Needs review', f"{int((df['needs_review'] == 1).sum()):,}")
        metrics[3].metric('News fields', f"{df['news_field'].nunique():,}")
        st.caption(f"Database total: {len(data):,} items · {analysed_count:,} analysed · {len(data) - analysed_count:,} awaiting analysis")
        st.progress(analysed_count / len(data), text='Analysis coverage across all saved items')
        if df.empty:
            st.info('No matching messages. Try All, a wider date range, or fewer filters.')
        else:
            signature = repr((mode, rooms, dates, fields, source_types, keyword))
            if st.session_state.get('filter_signature') != signature:
                st.session_state['feed_page'] = 1
                st.session_state['filter_signature'] = signature
            per_page = 20
            pages = max(1, (len(df) + per_page - 1) // per_page)
            st.session_state['feed_page'] = min(st.session_state.get('feed_page', 1), pages)
            page = st.number_input('Page', min_value=1, max_value=pages, step=1, key='feed_page')
            start = (page - 1) * per_page
            st.caption(f'{start + 1}–{min(start + per_page, len(df))} of {len(df):,} · {pages} pages')
            for _, row in df.iloc[start:start + per_page].iterrows():
                render_card(row)
    with priority:
        st.caption('Relevant stories ranked by saved relevance score. Scores do not measure investment quality or event importance.')
        selected = order_feed(df[df['relevant'] == 1], 'Highest relevance').head(10)
        if selected.empty:
            st.info('No relevant stories match these filters.')
        for _, row in selected.iterrows():
            render_card(row)
    with entities:
        st.caption('Mentions across matching stories. Tickers are AI candidates, not verified listings.')
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
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
        else:
            st.info('No saved entities match these filters.')
    with table:
        columns = [
            'message_date_kst', 'source_type', 'source_name', 'news_field',
            'analysed', 'relevant', 'relevance_score', 'event_date_kst',
            'summary_ko', 'summary_en', 'text', 'source_link',
        ]
        export = df[[c for c in columns if c in df.columns]]
        export = export.rename(columns={
            'message_date_kst': 'Date (KST)',
            'source_type': 'Source type',
            'source_name': 'Source',
            'news_field': 'News field',
            'analysed': 'Analysed',
            'relevant': 'Relevant',
            'relevance_score': 'Relevance score',
            'event_date_kst': 'Event date (KST)',
            'summary_ko': 'Summary (Korean)',
            'summary_en': 'Summary (English)',
            'text': 'Original message',
            'source_link': 'Original source',
        })
        if 'News field' in export:
            export['News field'] = export['News field'].map(
                lambda value: NEWS_FIELD_LABELS.get(str(value), format_label(value))
            )
        st.dataframe(export, width='stretch', hide_index=True)
        st.download_button('Download filtered CSV', export.to_csv(index=False).encode('utf-8-sig'), 'finboard_messages.csv', 'text/csv')
    with usage:
        st.caption('Recorded usage across Telegram and RSS analysis. Opening this dashboard makes no AI requests.')
        cols = st.columns(3)
        tokens = pd.to_numeric(data['total_tokens'], errors='coerce').sum()
        cost = pd.to_numeric(data['estimated_cost_usd'], errors='coerce').sum()
        cols[0].metric('Recorded tokens', f'{int(tokens):,}')
        cols[1].metric('Recorded estimated cost', f'${cost:.4f}')
        cols[2].metric('Analysed messages', f'{analysed_count:,}')
        if data['analysed'].any():
            usage_data = data.loc[data['analysed'], ['model', 'processed_at_utc', 'input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens', 'estimated_cost_usd']].rename(columns={
                'model': 'Model',
                'processed_at_utc': 'Processed (UTC)',
                'input_tokens': 'Input tokens',
                'cached_input_tokens': 'Cached input tokens',
                'output_tokens': 'Output tokens',
                'total_tokens': 'Total tokens',
                'estimated_cost_usd': 'Estimated cost (USD)',
            })
            st.dataframe(usage_data, width='stretch', hide_index=True)
    st.caption('AI summaries, event dates, and ticker mappings can be wrong; verify the original sources. Portfolio mixes are generic educational examples.')


if __name__ == '__main__':
    main()
