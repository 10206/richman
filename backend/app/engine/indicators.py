"""공통 지표 유틸 — 모든 함수는 pandas Series 입출력의 순수 함수.

z-score 윈도우는 docs/02 기준 2년(504거래일). 데이터가 짧으면 가용 구간으로 계산하되
최소 min_periods 미만이면 NaN을 유지한다 (신호 계산 단계에서 중립 처리).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

Z_WINDOW = 504  # 2년
Z_MIN_PERIODS = 126  # 최소 6개월


def squash(x: pd.Series | float) -> pd.Series | float:
    """tanh 압축 → [0, 1]. NaN은 0.5(중립)."""
    out = (np.tanh(x) + 1.0) / 2.0
    if isinstance(out, pd.Series):
        return out.fillna(0.5)
    return 0.5 if np.isnan(out) else float(out)


def rolling_z(s: pd.Series, window: int = Z_WINDOW, min_periods: int = Z_MIN_PERIODS) -> pd.Series:
    """스케일 정규화 z-score: z = x / rolling_std(x), ±4 클리핑.

    롤링 평균을 빼지 않는다 — 입력이 이미 '부호가 의미 있는' 변화량/괴리율이므로
    (금리 하락 = 음수 = 채권 호재 등), 평균을 빼면 지속적 추세가 중립으로 왜곡된다.
    변동성 대비 크기만 정규화해 "같은 25bp도 저변동기엔 큰 신호"가 되게 한다 (docs/03 §2).
    """
    std = s.rolling(window, min_periods=min_periods).std()
    z = s / std.where(std > 0)
    return z.clip(-4.0, 4.0)


def ma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=max(2, n // 2)).mean()


def pct_change_n(s: pd.Series, n: int) -> pd.Series:
    return s.pct_change(n)


def diff_n(s: pd.Series, n: int) -> pd.Series:
    """n일 차분 (금리 bp 변화 등 수준 변수용)."""
    return s.diff(n)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * volume).cumsum()


def up_volume_ratio(close: pd.Series, volume: pd.Series, n: int = 21) -> pd.Series:
    """최근 n일 상승일 거래량 비중. 0.5 = 중립."""
    up = (close.diff() > 0).astype(float) * volume
    total = volume.rolling(n, min_periods=n // 2).sum()
    ratio = up.rolling(n, min_periods=n // 2).sum() / total.replace(0.0, np.nan)
    return ratio


def ewma(s: pd.Series, halflife: float) -> pd.Series:
    return s.ewm(halflife=halflife, min_periods=1).mean()


def align_ffill(*series: pd.Series, index: pd.DatetimeIndex | None = None) -> list[pd.Series]:
    """여러 시계열을 공통 (합집합) 일자 인덱스에 정렬 후 ffill.

    거시 지표(주말 제외/발표 지연)와 가격 시계열을 섞어 쓸 때 사용.
    """
    if index is None:
        index = series[0].index
        for s in series[1:]:
            index = index.union(s.index)
    return [s.reindex(index).ffill() for s in series]
