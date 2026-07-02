"""국면 + 섹터 점수 + 신호를 한 번에 계산하는 공용 파이프라인.

백테스트(backtest/run_backtest.py)와 프로덕션 배치(jobs/daily_pipeline.py)가
같은 코드 경로를 쓴다 — 백테스트에서 검증된 로직이 그대로 서비스된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import regime as rg
from . import scoring as sc
from . import signals as sg
from .sectors import SECTOR_SIGNAL_PARAMS, SECTOR_SPEED, Sector
from .signals import SignalConfig


@dataclass
class MacroInputs:
    """시장 공통 거시 시계열 (일 인덱스, ffill 정렬 전 원본이어도 됨)."""

    benchmark_close: pd.Series      # S&P500 or KOSPI 종가
    vix: pd.Series                  # VIX (한국장도 글로벌 VIX 사용 — 가정 A7)
    hy_spread: pd.Series            # HY OAS (글로벌 공통)
    y_short: pd.Series              # 미 2Y / 한국 국고3Y
    y_long: pd.Series               # 미 10Y / 한국 국고10Y
    real_rate: pd.Series | None = None      # 금 전용 (DFII10)
    dollar_index: pd.Series | None = None   # 금 전용 (DTWEXBGS)
    news_sentiment: dict[Sector, pd.Series] = field(default_factory=dict)   # 필터 통과값 [0,1]
    geopolitical_boost: pd.Series | None = None                             # 금 전용 [0, 0.1]


@dataclass
class MarketState:
    """국면 계산 결과 (시장 단위)."""

    r_score: pd.Series
    l_score: pd.Series
    regime: pd.Series       # "G"/"R"/"T"/"F"
    local_trend: pd.Series  # 1.0/0.5/0.0


def compute_market_state(macro: MacroInputs) -> MarketState:
    idx = macro.benchmark_close.index
    vix = macro.vix.reindex(idx.union(macro.vix.index)).ffill().reindex(idx)
    hy = macro.hy_spread.reindex(idx.union(macro.hy_spread.index)).ffill().reindex(idx)
    y_s = macro.y_short.reindex(idx.union(macro.y_short.index)).ffill().reindex(idx)
    y_l = macro.y_long.reindex(idx.union(macro.y_long.index)).ffill().reindex(idx)

    r_score = rg.risk_score(macro.benchmark_close, vix, hy)
    l_score = rg.rate_direction_score(y_s, y_l)
    regime = rg.regime_series(rg.sticky_axis_state(r_score), rg.sticky_axis_state(l_score))
    local = rg.local_trend_state(macro.benchmark_close)
    return MarketState(r_score=r_score, l_score=l_score, regime=regime, local_trend=local)


def signal_config_for(sector: Sector) -> SignalConfig:
    enter, exit_, confirm = SECTOR_SIGNAL_PARAMS[sector]
    return SignalConfig(enter_long=enter, enter_cash=exit_, confirm_days=confirm)


def compute_sector_frame(
    sector: Sector,
    px: pd.DataFrame,          # columns: close, volume
    state: MarketState,
    macro: MacroInputs,
) -> pd.DataFrame:
    """섹터 하나의 (점수 분해 + 신호) 시계열.

    반환 컬럼: score, trend, volume, macro, w_*, stance, signal
    """
    pidx = px.index
    regime = state.regime.reindex(pidx).ffill()
    first_valid = regime.first_valid_index()
    if first_valid is None:
        raise ValueError(f"{sector}: 국면 시계열과 가격 시계열이 겹치지 않음")
    px = px.loc[first_valid:]
    pidx = px.index
    regime = regime.loc[first_valid:]

    def _al(s: pd.Series | None) -> pd.Series | None:
        if s is None:
            return None
        return s.reindex(pidx.union(s.index)).ffill().reindex(pidx)

    speed = SECTOR_SPEED[sector]
    T = sc.trend_component(px["close"], speed)
    V = sc.volume_component(px["close"], px["volume"], speed)

    r_score = _al(state.r_score)
    if sector == Sector.BONDS:
        M = sc.bond_macro_component(_al(macro.y_long), _al(macro.y_short), r_score)
    elif sector == Sector.GOLD:
        if macro.real_rate is None or macro.dollar_index is None:
            raise ValueError("금 섹터에는 real_rate, dollar_index가 필요")
        M = sc.gold_macro_component(
            _al(macro.real_rate), _al(macro.dollar_index), r_score,
            geopolitical_boost=_al(macro.geopolitical_boost),
        )
    else:
        M = sc.equity_macro_component(
            sector, regime, _al(state.local_trend), _al(macro.y_long),
            news=_al(macro.news_sentiment.get(sector)),
        )

    frame = sc.total_score(sector, regime, T, V, M)
    sig = sg.signal_series(frame["score"], signal_config_for(sector))
    frame["stance"] = sig["stance"]
    frame["signal"] = sig["signal"]
    frame["regime"] = regime
    return frame
