"""뉴스 감성 노이즈 필터 (docs/03 §3) — 폭·강도·지속 3중 게이트.

입력: 일간 섹터 감성 s_t [-1,1] 와 일간 관련 기사 수.
출력: M 컴포넌트에 들어갈 news 점수 [0,1] (게이트 미통과 = 0.5 중립).
"""

from __future__ import annotations

import pandas as pd

from .indicators import ewma, squash

MIN_ARTICLES_3D = 5
MIN_ABS_Z = 1.0
PERSIST_DAYS = 2


def news_signal(sentiment: pd.Series, article_count: pd.Series) -> pd.DataFrame:
    """반환 컬럼: z(강도), passed(게이트 통과 여부), news_score([0,1])."""
    fast = ewma(sentiment, halflife=3)
    slow = ewma(sentiment, halflife=21)
    std = sentiment.rolling(63, min_periods=10).std()
    z = ((fast - slow) / std.replace(0.0, float("nan"))).fillna(0.0)

    breadth = article_count.rolling(3, min_periods=1).sum() >= MIN_ARTICLES_3D
    magnitude = z.abs() >= MIN_ABS_Z
    same_sign = (z * z.shift(1)) > 0
    persist = same_sign & (z.shift(1).abs() >= MIN_ABS_Z)
    persist = persist.rolling(PERSIST_DAYS - 1, min_periods=1).max().astype(bool) if PERSIST_DAYS > 1 else magnitude

    passed = breadth & magnitude & persist
    score = pd.Series(0.5, index=sentiment.index)
    score[passed] = squash(z[passed])
    return pd.DataFrame({"z": z.round(3), "passed": passed, "news_score": score.round(3)})


def geopolitical_boost(geo_article_count: pd.Series, threshold: int = 5) -> pd.Series:
    """지정학 키워드 기사 수가 3일 합산 threshold 이상이면 금 위험회피 점수 +0.1 (docs/03 §3)."""
    hot = geo_article_count.rolling(3, min_periods=1).sum() >= threshold
    return hot.astype(float) * 0.10
