"""시세 수집 — Yahoo Finance (키 불필요, 미국 ETF/지수 일봉).

프로덕션에서는 KIS가 1차 소스이고 yfinance는 미국 시세 폴백 + 백테스트용 (가정 A5).
(stooq는 2026년 현재 안티봇 검증이 걸려 있어 제외.)
"""

from __future__ import annotations

import io

import httpx
import pandas as pd


def fetch_yahoo_daily(symbol: str, start: str = "2014-01-01") -> pd.DataFrame:
    """야후 일봉 (수정주가). 컬럼: open, high, low, close, volume (DatetimeIndex).

    symbol 예: 'SMH', 'GLD', '^GSPC'
    """
    import yfinance as yf

    df = yf.download(symbol, start=start, progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        raise ValueError(f"yahoo: no data for {symbol!r}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]].sort_index()


def fetch_fred_csv(series_ids: list[str], timeout: float = 30.0) -> pd.DataFrame:
    """FRED fredgraph CSV — API 키 불필요. 컬럼 = series_ids, '.' 결측은 NaN.

    다중 시리즈를 한 번에 요청하면 ZIP으로 응답하므로 시리즈별 개별 요청 후 조인.
    """
    frames = []
    for sid in series_ids:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), na_values=".")
        date_col = df.columns[0]  # 'DATE' 또는 'observation_date'
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col)
        df.index.name = "date"
        frames.append(df.astype(float))
    return pd.concat(frames, axis=1, join="outer").sort_index()
