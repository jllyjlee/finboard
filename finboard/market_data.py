from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    market: str
    currency: str
    yahoo_symbol: str


WATCHLIST = (
    Asset("005930", "Samsung Electronics", "KRX", "KRW", "005930.KS"),
    Asset("000660", "SK hynix", "KRX", "KRW", "000660.KS"),
    Asset("005380", "Hyundai Motor", "KRX", "KRW", "005380.KS"),
    Asset("373220", "LG Energy Solution", "KRX", "KRW", "373220.KS"),
    Asset("035420", "NAVER", "KRX", "KRW", "035420.KS"),
    Asset("069500", "KODEX 200 ETF", "KRX", "KRW", "069500.KS"),
    Asset("NVDA", "NVIDIA", "US", "USD", "NVDA"),
    Asset("MSFT", "Microsoft", "US", "USD", "MSFT"),
    Asset("AAPL", "Apple", "US", "USD", "AAPL"),
    Asset("AMZN", "Amazon", "US", "USD", "AMZN"),
    Asset("GOOGL", "Alphabet", "US", "USD", "GOOGL"),
    Asset("TSLA", "Tesla", "US", "USD", "TSLA"),
    Asset("SPY", "S&P 500 ETF", "US", "USD", "SPY"),
    Asset("QQQ", "Nasdaq-100 ETF", "US", "USD", "QQQ"),
    Asset("BND", "US Total Bond Market ETF", "US", "USD", "BND"),
)

ASSETS_BY_SYMBOL = {asset.symbol.upper(): asset for asset in WATCHLIST}


def asset_for_entity(entity: dict) -> Asset | None:
    ticker = entity.get("ticker_candidate")
    exchange = entity.get("exchange")
    yahoo_symbol = quote_symbol_for_entity(ticker, exchange)
    if not yahoo_symbol:
        return None
    candidate = str(ticker).strip().upper()
    existing = ASSETS_BY_SYMBOL.get(candidate)
    if existing and existing.yahoo_symbol == yahoo_symbol:
        return existing
    is_krx = yahoo_symbol.endswith((".KS", ".KQ"))
    return Asset(
        symbol=candidate,
        name=str(entity.get("normalized_name") or entity.get("mention") or candidate),
        market="KRX" if is_krx else str(exchange or "US"),
        currency="KRW" if is_krx else "USD",
        yahoo_symbol=yahoo_symbol,
    )


def quote_symbol_for_entity(ticker: str | None, exchange: str | None) -> str | None:
    if not ticker:
        return None
    candidate = ticker.strip().upper()
    if not candidate:
        return None
    if candidate in ASSETS_BY_SYMBOL:
        return ASSETS_BY_SYMBOL[candidate].yahoo_symbol
    if candidate.isdigit() and exchange and exchange.upper() in {"KRX", "KOSPI", "KOSDAQ"}:
        suffix = ".KQ" if exchange.upper() == "KOSDAQ" else ".KS"
        return candidate + suffix
    return candidate


def fetch_quotes(assets: tuple[Asset, ...] = WATCHLIST) -> list[dict]:
    """Fetch recent daily closes via Yahoo Finance's public chart data."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            "Market quotes require yfinance. Install project dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    if not assets:
        return []

    downloaded = yf.download(
        tickers=[asset.yahoo_symbol for asset in assets],
        period="5d",
        interval="1d",
        auto_adjust=False,
        actions=False,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    quotes = []
    for asset in assets:
        if downloaded.empty:
            history = downloaded
        elif getattr(downloaded.columns, "nlevels", 1) > 1:
            symbols = downloaded.columns.get_level_values(0)
            if asset.yahoo_symbol in symbols:
                history = downloaded[asset.yahoo_symbol]
            elif asset.yahoo_symbol in downloaded.columns.get_level_values(1):
                history = downloaded.xs(asset.yahoo_symbol, axis=1, level=1)
            else:
                history = downloaded.iloc[0:0]
        else:
            history = downloaded
        closes = history["Close"].dropna() if not history.empty and "Close" in history else []
        if len(closes) == 0:
            quotes.append(
                {
                    "asset": asset,
                    "price": None,
                    "change_pct": None,
                    "as_of": None,
                }
            )
            continue

        price = float(closes.iloc[-1])
        adjusted = (
            history["Adj Close"].dropna()
            if "Adj Close" in history
            else closes
        )
        previous = float(adjusted.iloc[-2]) if len(adjusted) > 1 else None
        change_pct = ((float(adjusted.iloc[-1]) / previous) - 1) * 100 if previous else None
        as_of = history.index[-1].date().isoformat()
        quotes.append(
            {
                "asset": asset,
                "price": price,
                "change_pct": change_pct,
                "as_of": as_of,
            }
        )
    return quotes
