import os
from typing import Literal

from pydantic import BaseModel, Field
from openai import OpenAI

client = None


def get_client() -> OpenAI:
    global client

    if client is None:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_ADMIN_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing OpenAI credentials. Set OPENAI_API_KEY before calling the AI analyzer."
            )
        client = OpenAI(api_key=api_key)

    return client


# 1. Define allowed entity types

EntityType = Literal[
    "company",
    "security",
    "person",
    "sector",
    "industry",
    "commodity",
    "currency",
    "cryptocurrency",
    "country",
    "organization",
    "product",
    "index",
    "economic_indicator",
    "other",
]


# 2. Define the output schema

class FinancialEntity(BaseModel):
    mention: str
    normalized_name: str | None
    entity_type: EntityType

    ticker_candidate: str | None
    exchange: str | None

    ticker_confidence: int = Field(
        ge=0,
        le=100
    )

InformationStatus = Literal[
    "confirmed",
    "reported",
    "rumor",
    "opinion",
    "analysis",
    "unknown",
]

Category = Literal[
    "company_event",
    "earnings",
    "macro",
    "industry",
    "regulation",
    "market",
    "research",
    "commodity",
    "currency",
    "crypto",
    "geopolitics",
    "other",
]

NewsField = Literal[
    "business_finance",
    "economy",
    "politics",
    "healthcare",
    "ai_technology",
    "science",
    "sports",
    "geopolitics",
    "energy_commodities",
    "crypto",
    "other",
]


class MessageAnalysis(BaseModel):
    relevant: bool

    relevance_score: int = Field(
        ge=0,
        le=100
    )

    category: Category
    news_field: NewsField
    event_type: str
    information_status: InformationStatus

    entities: list[FinancialEntity]

    needs_review: bool
    summary_ko: str
    summary_en: str
    event_date_kst: str | None


SYSTEM_PROMPT = """
You are a financial-information classification system.

Your task is to analyze messages collected from financial Telegram channels.

Determine whether each message contains information relevant to financial
markets, investing, companies, securities, macroeconomics, commodities,
currencies, cryptocurrencies, regulation, earnings, corporate events,
industry developments, or other potentially market-relevant developments.
Also classify the message into the most suitable general news field, even
when it is not directly finance-related.

Rules:

1. Do not invent information that is not contained in the message.

2. A message may be relevant even if it does not mention a stock ticker.

3. Extract entities explicitly mentioned in the message.

4. For company tickers:
   - include the ticker only when you are highly confident;
   - otherwise return null.

5. Advertising, greetings, unrelated conversation, repeated channel
   promotion, and non-financial chatter should normally be marked irrelevant.

6. relevance_score:
   0 = completely irrelevant
   100 = clearly material financial information

7. needs_review should be true when the classification or entity mapping
   is genuinely ambiguous.

8. Do not provide investment recommendations.

9. For listed securities:
   - ticker_candidate should contain only the native ticker/code.
   - Do not append provider-specific suffixes such as .KS, .KQ, .L, etc.
   - Return the exchange separately.

   Examples:

   Samsung Electronics:
   ticker_candidate = "005930"
   exchange = "KRX"

   NVIDIA:
   ticker_candidate = "NVDA"
   exchange = "NASDAQ"

10. For information_status, return exactly one of:
    confirmed,
    reported,
    rumor,
    opinion,
    analysis,
    unknown.

11. news_field must be exactly one of:
    business_finance, economy, politics, healthcare, ai_technology,
    science, sports, geopolitics, energy_commodities, crypto, other.

12. Write a concise, factual summary of no more than two short sentences in
    both Korean and English. Translate faithfully when the source is in one
    language. Do not add facts or investment advice. If the source is too
    unclear to summarize, say so briefly in both languages.

13. event_date_kst is only for a specific, explicitly stated current or
    upcoming event date. Return YYYY-MM-DD in Korea Standard Time if the
    date can be determined from the message; otherwise return null. Never
    infer a date from when the message was posted.

Return only the structured schema requested.
"""


# 4. Put the API function underneath

def analyze_message(text: str) -> MessageAnalysis:
    response = get_client().responses.parse(
        model="gpt-5.6-luna",

        input=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": text,
            },
        ],

        text_format=MessageAnalysis,
    )

    return response.output_parsed


def analyze_message_with_usage(text: str):
    response = get_client().responses.parse(
        model="gpt-5.6-luna",
        input=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": text
            }
        ],
        text_format=MessageAnalysis
    )

    result = response.output_parsed

    usage = response.usage

    cached_tokens = 0

    if (
        usage.input_tokens_details is not None
        and usage.input_tokens_details.cached_tokens is not None
    ):
        cached_tokens = usage.input_tokens_details.cached_tokens

    usage_data = {
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }

    return result, usage_data