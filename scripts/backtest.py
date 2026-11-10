#!/usr/bin/env python3
"""backtrader SMA-cross backtest.

Fetches price data DIRECTLY from Yahoo's chart API (never yfinance),
parses it into a pandas OHLC DataFrame, and feeds it to backtrader
via bt.feeds.PandasData.

Strategy: buy when close crosses above SMA20, close the position
when close crosses below SMA20. Stake ~95% of available cash.

Usage:
    python scripts/backtest.py [--ticker AAPL] [--cash 100000] [--sma-period 20] [--years 3]

Defaults are the pilot: AAPL, last ~3 years, starting cash 100000.
The ticker is a CLI argument — nothing is hardcoded beyond pilot defaults.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import backtrader as bt
import pandas as pd
import requests


def fetch_yahoo_chart(ticker: str, years: int = 3) -> pd.DataFrame:
    """Fetch daily OHLC from Yahoo chart API directly via requests."""
    now = int(time.time())
    period2 = now
    period1 = now - int(years * 365.25 * 24 * 3600)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    print(f"Fetching {url}")
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo chart error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RuntimeError("Yahoo chart returned no results")
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators", {})
    quote_list = indicators.get("quote") or []
    if not quote_list:
        raise RuntimeError("Yahoo chart returned no quote data")
    quote = quote_list[0]

    df = pd.DataFrame(
        {
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        },
        index=pd.to_datetime(timestamps, unit="s", utc=True),
    )
    # backtrader PandasData expects a DatetimeIndex; keep tz-naive dates
    df.index = df.index.tz_convert(None).normalize()
    df.index.name = "datetime"
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if df.empty:
        raise RuntimeError("No usable OHLC rows after cleaning")
    return df


class SmaCrossStrategy(bt.Strategy):
    params = (("sma_period", 20),)

    def __init__(self):
        self.sma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.sma_period
        )
        self.crossover = bt.indicators.CrossOver(self.data.close, self.sma)
        self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.crossover > 0:
                cash = self.broker.getcash()
                price = self.data.close[0]
                if price > 0:
                    size = int((cash * 0.95) / price)
                    if size > 0:
                        self.order = self.buy(size=size)
        else:
            if self.crossover < 0:
                self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


def main():
    parser = argparse.ArgumentParser(description="backtrader SMA-cross backtest")
    parser.add_argument("ticker", nargs="?", default="AAPL", help="Ticker symbol (default: AAPL)")
    parser.add_argument("--ticker", dest="ticker_opt", default=None, help="Ticker symbol (alternative flag)")
    parser.add_argument("--cash", type=float, default=100000, help="Starting cash (default: 100000)")
    parser.add_argument("--sma-period", type=int, default=20, help="SMA period (default: 20)")
    parser.add_argument("--years", type=int, default=3, help="Years of history to fetch (default: 3)")
    args = parser.parse_args()
    ticker = (args.ticker_opt or args.ticker).upper()

    df = fetch_yahoo_chart(ticker, years=args.years)
    print(f"Rows: {len(df)}  Range: {df.index[0].date()} to {df.index[-1].date()}")

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(args.cash)
    # No commission/slippage assumptions in the pilot (defaults)
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    cerebro.addstrategy(SmaCrossStrategy, sma_period=args.sma_period)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    start_value = cerebro.broker.getvalue()
    print(f"Starting Portfolio Value: {start_value:.2f}")
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    print(f"Final Portfolio Value: {final_value:.2f}")

    strat = results[0]
    trade_analysis = strat.analyzers.trades.get_analysis()
    # TradeAnalyzer: total.closed is the number of completed (closed) trades
    total_closed = 0
    try:
        total_closed = int(trade_analysis.get("total", {}).get("closed", 0) or 0)
    except Exception:
        total_closed = 0

    total_return_pct = ((final_value - start_value) / start_value * 100.0) if start_value else 0.0

    stats = {
        "ticker": ticker,
        "strategy": f"SMA{args.sma_period} cross (buy on cross above, close on cross below, 95% cash stake)",
        "start_value": round(float(start_value), 2),
        "final_value": round(float(final_value), 2),
        "total_return_pct": round(float(total_return_pct), 4),
        "completed_trades": total_closed,
        "data_rows": int(len(df)),
        "date_range": {
            "start": str(df.index[0].date()),
            "end": str(df.index[-1].date()),
        },
        "starting_cash": float(args.cash),
        "sma_period": int(args.sma_period),
    }

    print(json.dumps(stats, indent=2))
    os.makedirs("results", exist_ok=True)
    with open("results/stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print("Wrote results/stats.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
