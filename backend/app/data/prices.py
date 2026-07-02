"""시세 소스 정책 — KIS 1차 / yfinance 폴백 (docs/03 §1, 가정 A5).

정책:
  - KR 섹터: KIS 키가 있으면 KIS 국내 일봉, 없으면 yfinance "{code}.KS" 폴백.
  - US 섹터: yfinance 기본 (KIS 해외시세는 실검증 전이라 명시 opt-in 안 함).
  - 벤치마크: KOSPI=^KS11, S&P500=^GSPC (yfinance).
  - 반환은 항상 close/volume 컬럼의 DataFrame (DatetimeIndex) — 엔진 입력 규격.
"""

from __future__ import annotations

import logging

import pandas as pd

from app.data.market import fetch_yahoo_daily
from app.engine.sectors import SECTOR_PROXIES, Market, Sector

logger = logging.getLogger(__name__)

BENCHMARKS = {Market.KR: "^KS11", Market.US: "^GSPC"}


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["close", "volume"]].copy()
    out = out.dropna(subset=["close"]).sort_index()
    out["volume"] = out["volume"].fillna(0.0)
    return out


def get_sector_prices(
    market: Market,
    sector: Sector,
    start: str,
    kis_client=None,
) -> pd.DataFrame:
    """섹터 프록시 일봉 (close/volume).

    kis_client: app.data.kis.KISClient 인스턴스 (KR + 키 보유 시에만 전달).
    """
    code = SECTOR_PROXIES[market][sector]
    if market == Market.KR:
        if kis_client is not None:
            try:
                return _normalize(kis_client.fetch_domestic_daily(code, start))
            except Exception as e:  # noqa: BLE001 — 폴백 경로가 있으므로 광범위 캐치 허용
                logger.warning("KIS 국내 시세 실패(%s %s): %s → yfinance 폴백", sector.value, code, e)
        return _normalize(fetch_yahoo_daily(f"{code}.KS", start))
    # US: yfinance 기본
    return _normalize(fetch_yahoo_daily(code, start))


def get_benchmark_prices(market: Market, start: str) -> pd.DataFrame:
    """시장 벤치마크 지수 일봉 (KOSPI/^KS11, S&P500/^GSPC)."""
    return _normalize(fetch_yahoo_daily(BENCHMARKS[market], start))
