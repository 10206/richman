"""거시 국면 분류 (docs/01).

모든 함수는 시계열 입출력의 순수 함수 — 마지막 값만 취하면 오늘의 국면,
전체를 취하면 백테스트용 국면 시계열이 된다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import diff_n, ma, pct_change_n, rolling_z
from .sectors import Regime

AXIS_BAND = 0.10  # 히스테리시스 밴드 (docs/01 §2)
CONFIRM_DAYS = 2


def risk_score(spx_close: pd.Series, vix: pd.Series, hy_spread: pd.Series) -> pd.Series:
    """R축 — 위험선호 점수 [-1, +1]. 양수 = 위험선호(risk-on)."""
    # 개별 컴포넌트가 결측/무변동이면 중립(0)으로 — 하나의 NaN이 전체를 오염시키지 않게
    trend = rolling_z(spx_close / ma(spx_close, 200) - 1.0).fillna(0.0)
    vix_level = (-(vix - 20.0) / 10.0).clip(-1.0, 1.0).fillna(0.0)
    hy_widening = (-rolling_z(diff_n(hy_spread, 63))).fillna(0.0)
    momentum = rolling_z(pct_change_n(spx_close, 63)).fillna(0.0)
    raw = 0.35 * trend + 0.30 * vix_level + 0.25 * hy_widening + 0.10 * momentum
    return np.tanh(raw.astype(float))


def rate_direction_score(y_short: pd.Series, y_long: pd.Series) -> pd.Series:
    """L축 — 금리 방향 점수 [-1, +1]. 양수 = 금리 상승기.

    미국: y_short=DGS2, y_long=DGS10 / 한국: 국고3년, 국고10년 (docs/01 §2).
    """
    raw = (
        0.45 * rolling_z(diff_n(y_short, 63)).fillna(0.0)
        + 0.40 * rolling_z(diff_n(y_long, 63)).fillna(0.0)
        + 0.15 * rolling_z(diff_n(y_long, 21)).fillna(0.0)
    )
    return np.tanh(raw.astype(float))


def sticky_axis_state(score: pd.Series, band: float = AXIS_BAND, confirm_days: int = CONFIRM_DAYS) -> pd.Series:
    """연속 점수 → 히스테리시스 + 확인기간이 적용된 이진 상태 (+1/-1).

    밴드(±band) 안에서는 직전 상태 유지, 밴드 밖 새 상태는 confirm_days 연속일 때만 전환.
    초기 상태는 첫 유효값의 부호.
    """
    states = np.zeros(len(score))
    current = 0.0
    pending: float | None = None
    pending_run = 0
    values = score.to_numpy()
    for i, v in enumerate(values):
        if np.isnan(v):
            states[i] = current
            continue
        if current == 0.0:  # 초기화
            current = 1.0 if v >= 0 else -1.0
            states[i] = current
            continue
        candidate = 1.0 if v > band else (-1.0 if v < -band else current)
        if candidate != current:
            pending_run = pending_run + 1 if pending == candidate else 1
            pending = candidate
            if pending_run >= confirm_days:
                current = candidate
                pending, pending_run = None, 0
        else:
            pending, pending_run = None, 0
        states[i] = current
    return pd.Series(states, index=score.index)


def regime_series(risk_state: pd.Series, rate_state: pd.Series) -> pd.Series:
    """R/L 이진 상태 → 4국면 (docs/01 §2 표).

    값은 평문 문자열 "G"/"R"/"T"/"F" (object dtype) — str-Enum을 그대로 담으면
    pandas 3.x가 str dtype으로 추론하면서 Enum 비교가 깨진다.
    """
    risk_state, rate_state = risk_state.align(rate_state, join="inner")

    def _classify(r: float, l: float) -> str:
        if r > 0:
            return (Regime.R if l > 0 else Regime.G).value
        return (Regime.T if l > 0 else Regime.F).value

    return pd.Series(
        [_classify(r, l) for r, l in zip(risk_state, rate_state)],
        index=risk_state.index,
        dtype=object,
    )


def local_trend_state(index_close: pd.Series) -> pd.Series:
    """시장 하위상태 (docs/01 §3): 강세 1.0 / 중립 0.5 / 약세 0.0."""
    ma20, ma60, ma120 = ma(index_close, 20), ma(index_close, 60), ma(index_close, 120)
    bull = (index_close > ma120) & (ma20 > ma60)
    bear = (index_close < ma120) & (ma20 < ma60)
    out = pd.Series(0.5, index=index_close.index)
    out[bull] = 1.0
    out[bear] = 0.0
    out[ma120.isna()] = 0.5
    return out
