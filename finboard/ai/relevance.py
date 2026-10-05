from typing import Literal
from pydantic import BaseModel, Field
from openai import OpenAI

client = OpenAI()


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


class MessageAnalysis(BaseModel):
    relevant: bool

    relevance_score: int = Field(
        ge=0,
        le=100
    )

    category: Category
    event_type: str
    information_status: InformationStatus

    entities: list[FinancialEntity]

    needs_review: bool


SYSTEM_PROMPT = """
You are a financial-information classification system.

Your task is to analyze messages collected from financial Telegram channels.

Determine whether each message contains information relevant to financial
markets, investing, companies, securities, macroeconomics, commodities,
currencies, cryptocurrencies, regulation, earnings, corporate events,
industry developments, or other potentially market-relevant developments.

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

Return only the structured schema requested.
"""


# 4. Put the API function underneath

def analyze_message(text: str) -> MessageAnalysis:

    response = client.responses.parse(
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

    response = client.responses.parse(
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