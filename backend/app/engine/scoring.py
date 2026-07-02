"""섹터 스코어링 (docs/02).

컴포넌트(T/V/M)는 [0,1], 총점은 [0,100]. 전부 시계열 순수 함수.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import (
    diff_n,
    ma,
    obv,
    pct_change_n,
    rolling_z,
    squash,
    up_volume_ratio,
)
from .sectors import GROWTH_SECTORS, Regime, Sector, weights_for


# 컴포넌트 속도별 룩백 (docs/02 §1, 백테스트 근거는 docs/04 §4):
#  fast — 고베타 성장 섹터용 (반도체/로봇): 추세 전환을 빠르게 포착
#  slow — 방어/거시 섹터용 (전력/헬스케어/금/국채): 평균회귀 노이즈에 휘둘리지 않게
_TREND_LOOKBACKS = {"fast": (60, 20, 63), "slow": (120, 60, 126)}
_VOLUME_LOOKBACKS = {"fast": 21, "slow": 42}


def trend_component(close: pd.Series, speed: str = "fast") -> pd.Series:
    """T — 추세 (docs/02 §1)."""
    base, short, ret_n = _TREND_LOOKBACKS[speed]
    t_raw = (
        0.40 * rolling_z(close / ma(close, base) - 1.0)
        + 0.30 * rolling_z(ma(close, short) / ma(close, base) - 1.0)
        + 0.30 * rolling_z(pct_change_n(close, ret_n))
    )
    return squash(t_raw)


def volume_component(close: pd.Series, volume: pd.Series, speed: str = "fast") -> pd.Series:
    """V — 방향성 거래량 (docs/02 §1)."""
    n = _VOLUME_LOOKBACKS[speed]
    uvr = up_volume_ratio(close, volume, n)
    obv_z = rolling_z(diff_n(obv(close, volume), n))
    vol_z = rolling_z(ma(volume, n))
    amp = 1.0 + 0.3 * vol_z.clip(0.0, 2.0)
    v_raw = 2.5 * (uvr - 0.5) * amp + 0.5 * obv_z
    return squash(v_raw)


def _risk_aversion_score(risk_score_series: pd.Series) -> pd.Series:
    """위험회피일수록 1에 가깝게. R_score는 [-1,1] (양수=위험선호)."""
    return 1.0 - squash(risk_score_series * 1.5)


def bond_macro_component(
    y10: pd.Series,
    y2: pd.Series,
    risk_score_series: pd.Series,
) -> pd.Series:
    """국채 M (docs/02 §3): 금리방향 45% + 커브 25% + 위험회피 30%."""
    rate = squash(-rolling_z(diff_n(y10, 63)))
    curve = squash(rolling_z(diff_n(y10 - y2, 63)))
    risk_av = _risk_aversion_score(risk_score_series)
    return 0.45 * rate + 0.25 * curve + 0.30 * risk_av


def gold_macro_component(
    real_rate: pd.Series,
    dollar_index: pd.Series,
    risk_score_series: pd.Series,
    geopolitical_boost: pd.Series | None = None,
) -> pd.Series:
    """금 M (docs/02 §3): 실질금리 40% + 달러 30% + 위험회피 30%."""
    rr = squash(-rolling_z(diff_n(real_rate, 63)))
    dollar = squash(-rolling_z(diff_n(dollar_index, 63)))
    risk_av = _risk_aversion_score(risk_score_series)
    if geopolitical_boost is not None:
        risk_av = (risk_av + geopolitical_boost.reindex(risk_av.index).fillna(0.0)).clip(0.0, 1.0)
    return 0.40 * rr + 0.30 * dollar + 0.30 * risk_av


def rate_sensitivity(y10: pd.Series, sector: Sector) -> pd.Series:
    """성장주 금리 급변 페널티/보너스 (docs/02 §3, 불감대 ±50bp/63일)."""
    chg = diff_n(y10, 63)  # 퍼센트포인트 단위
    full = pd.Series(0.5, index=y10.index)
    full[chg > 0.50] = 0.0
    full[chg < -0.50] = 1.0
    if sector in GROWTH_SECTORS:
        return full
    return 0.5 + (full - 0.5) * 0.5  # 방어/혼합 섹터는 절반 강도


def equity_macro_component(
    sector: Sector,
    regime: pd.Series,
    local_trend: pd.Series,
    y10: pd.Series,
    news: pd.Series | None = None,
) -> pd.Series:
    """주식 섹터 M (docs/02 §3)."""
    from .sectors import REGIME_BIAS

    bias = regime.map(lambda r: (REGIME_BIAS[sector][Regime(r)] + 2) / 4.0)
    if news is None:
        news = pd.Series(0.5, index=regime.index)
    news = news.reindex(regime.index).fillna(0.5)
    local = local_trend.reindex(regime.index).ffill().fillna(0.5)
    rs = rate_sensitivity(y10, sector).reindex(regime.index).ffill().fillna(0.5)
    return 0.50 * bias + 0.25 * local + 0.15 * news + 0.10 * rs


def total_score(
    sector: Sector,
    regime: pd.Series,
    trend: pd.Series,
    volume: pd.Series,
    macro: pd.Series,
) -> pd.DataFrame:
    """총점 + 컴포넌트 분해 (UI 표시용). 국면별 가중치 적용 (docs/02 §2).

    반환 컬럼: score, trend, volume, macro, w_trend, w_volume, w_macro
    """
    idx = regime.index
    trend = trend.reindex(idx).fillna(0.5)
    volume = volume.reindex(idx).fillna(0.5)
    macro = macro.reindex(idx).fillna(0.5)

    w = regime.map(lambda r: weights_for(sector, Regime(r)))
    w_t = w.map(lambda x: x.trend).astype(float)
    w_v = w.map(lambda x: x.volume).astype(float)
    w_m = w.map(lambda x: x.macro).astype(float)

    score = 100.0 * (w_t * trend + w_v * volume + w_m * macro)
    return pd.DataFrame(
        {
            "score": score.round(1),
            "trend": trend.round(3),
            "volume": volume.round(3),
            "macro": macro.round(3),
            "w_trend": w_t,
            "w_volume": w_v,
            "w_macro": w_m,
        },
        index=idx,
    )
