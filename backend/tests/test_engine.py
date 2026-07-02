"""시그널 엔진 단위 테스트 — 합성 데이터로 방향성/경계 조건 검증."""

import numpy as np
import pandas as pd
import pytest

from app.engine import regime as rg
from app.engine import scoring as sc
from app.engine import signals as sg
from app.engine.news_filter import geopolitical_boost, news_signal
from app.engine.sectors import Regime, Sector, weights_for
from app.engine.signals import Signal, SignalConfig, Stance


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2018-01-01", periods=n)


def _noisy(start: float, stop: float, n: int, seed: int = 0, scale: float = 0.02) -> np.ndarray:
    """선형 추세 + 소량 노이즈 — 순수 linspace는 diff의 std가 0이라 z-score가 정의되지 않음."""
    rng = np.random.default_rng(seed)
    return np.linspace(start, stop, n) + scale * rng.standard_normal(n)


@pytest.fixture
def n():
    return 800


@pytest.fixture
def uptrend(n):
    idx = _dates(n)
    rng = np.random.default_rng(42)
    return pd.Series(100 * np.cumprod(1 + 0.0008 + 0.01 * rng.standard_normal(n)), index=idx)


@pytest.fixture
def downtrend(n):
    idx = _dates(n)
    rng = np.random.default_rng(7)
    return pd.Series(100 * np.cumprod(1 - 0.0008 + 0.01 * rng.standard_normal(n)), index=idx)


class TestRegime:
    def test_risk_score_bull_vs_bear(self, uptrend, downtrend, n):
        idx = _dates(n)
        vix_low = pd.Series(14.0, index=idx)
        vix_high = pd.Series(32.0, index=idx)
        hy_stable = pd.Series(3.5, index=idx)
        hy_widening = pd.Series(_noisy(3.0, 8.0, n, 11), index=idx)

        r_on = rg.risk_score(uptrend, vix_low, hy_stable)
        r_off = rg.risk_score(downtrend, vix_high, hy_widening)
        assert r_on.iloc[-1] > 0.1
        assert r_off.iloc[-1] < -0.1

    def test_rate_direction(self, n):
        idx = _dates(n)
        rising = pd.Series(_noisy(1.0, 5.0, n, 1), index=idx)
        falling = pd.Series(_noisy(5.0, 1.0, n, 2), index=idx)
        assert rg.rate_direction_score(rising, rising).iloc[-1] > 0.1
        assert rg.rate_direction_score(falling, falling).iloc[-1] < -0.1

    def test_sticky_axis_hysteresis(self):
        idx = _dates(10)
        # 밴드(±0.1) 안에서 진동 → 초기 상태(+1) 유지
        s = pd.Series([0.5, 0.05, -0.05, 0.08, -0.09, 0.0, 0.05, -0.08, 0.02, -0.01], index=idx)
        st = rg.sticky_axis_state(s)
        assert (st == 1.0).all()

    def test_sticky_axis_confirmation(self):
        idx = _dates(6)
        # 하루짜리 급락은 무시, 2일 연속이면 전환
        s = pd.Series([0.5, 0.5, -0.5, 0.5, -0.5, -0.5], index=idx)
        st = rg.sticky_axis_state(s)
        assert st.iloc[3] == 1.0   # 1일 급락 후 복귀 → 유지
        assert st.iloc[-1] == -1.0  # 2일 연속 → 전환

    def test_regime_mapping(self):
        idx = _dates(4)
        risk = pd.Series([1.0, 1.0, -1.0, -1.0], index=idx)
        rate = pd.Series([-1.0, 1.0, 1.0, -1.0], index=idx)
        out = rg.regime_series(risk, rate)
        assert list(out) == [Regime.G, Regime.R, Regime.T, Regime.F]

    def test_local_trend(self, uptrend, downtrend):
        assert rg.local_trend_state(uptrend).iloc[-1] == 1.0
        assert rg.local_trend_state(downtrend).iloc[-1] == 0.0


class TestScoring:
    def test_trend_component_direction(self, uptrend, downtrend):
        assert sc.trend_component(uptrend).iloc[-1] > 0.55
        assert sc.trend_component(downtrend).iloc[-1] < 0.45

    def test_volume_component_accumulation(self, n):
        """상승일에 거래량이 실리면 V > 0.5, 하락일에 실리면 V < 0.5."""
        idx = _dates(n)
        rng = np.random.default_rng(3)
        ret = 0.01 * rng.standard_normal(n)
        close = pd.Series(100 * np.cumprod(1 + ret), index=idx)
        vol_bull = pd.Series(np.where(ret > 0, 2e6, 5e5), index=idx)
        vol_bear = pd.Series(np.where(ret < 0, 2e6, 5e5), index=idx)
        assert sc.volume_component(close, vol_bull).iloc[-1] > 0.5
        assert sc.volume_component(close, vol_bear).iloc[-1] < 0.5

    def test_bond_macro_rates_falling_is_bullish(self, n):
        idx = _dates(n)
        y10_fall = pd.Series(_noisy(5.0, 2.0, n, 21), index=idx)
        y2_fall = pd.Series(_noisy(5.5, 1.5, n, 22), index=idx)
        y10_rise = pd.Series(_noisy(2.0, 5.0, n, 23), index=idx)
        y2_rise = pd.Series(_noisy(1.5, 5.5, n, 24), index=idx)
        risk_off = pd.Series(-0.8, index=idx)
        risk_on = pd.Series(0.8, index=idx)
        bull = sc.bond_macro_component(y10_fall, y2_fall, risk_off).iloc[-1]
        bear = sc.bond_macro_component(y10_rise, y2_rise, risk_on).iloc[-1]
        assert bull > 0.6 > bear

    def test_gold_macro(self, n):
        idx = _dates(n)
        rr_fall = pd.Series(_noisy(2.0, -1.0, n, 31), index=idx)
        dxy_fall = pd.Series(_noisy(110, 90, n, 32, scale=0.3), index=idx)
        rr_rise = pd.Series(_noisy(-1.0, 2.0, n, 33), index=idx)
        dxy_rise = pd.Series(_noisy(90, 110, n, 34, scale=0.3), index=idx)
        risk_off = pd.Series(-0.8, index=idx)
        risk_on = pd.Series(0.8, index=idx)
        bull = sc.gold_macro_component(rr_fall, dxy_fall, risk_off).iloc[-1]
        bear = sc.gold_macro_component(rr_rise, dxy_rise, risk_on).iloc[-1]
        assert bull > 0.6 > bear

    def test_rate_sensitivity_deadband(self, n):
        idx = _dates(n)
        flat = pd.Series(3.0 + 0.001 * np.arange(n) % 0.1, index=idx)
        spike = pd.Series(np.concatenate([np.full(n - 63, 3.0), np.linspace(3.0, 4.0, 63)]), index=idx)
        assert sc.rate_sensitivity(flat, Sector.SEMICONDUCTOR).iloc[-1] == 0.5
        assert sc.rate_sensitivity(spike, Sector.SEMICONDUCTOR).iloc[-1] == 0.0
        assert sc.rate_sensitivity(spike, Sector.HEALTHCARE).iloc[-1] == 0.25

    def test_equity_macro_regime_bias(self, n):
        idx = _dates(n)
        y10 = pd.Series(3.0, index=idx)
        local = pd.Series(0.5, index=idx)
        reg_g = pd.Series(Regime.G, index=idx)
        reg_t = pd.Series(Regime.T, index=idx)
        m_g = sc.equity_macro_component(Sector.SEMICONDUCTOR, reg_g, local, y10).iloc[-1]
        m_t = sc.equity_macro_component(Sector.SEMICONDUCTOR, reg_t, local, y10).iloc[-1]
        assert m_g > 0.6 > 0.4 > m_t

    def test_weights_regime_switch(self):
        assert weights_for(Sector.SEMICONDUCTOR, Regime.G).trend == 0.50
        assert weights_for(Sector.SEMICONDUCTOR, Regime.T).macro == 0.45
        assert weights_for(Sector.BONDS, Regime.G) == weights_for(Sector.BONDS, Regime.T)

    def test_total_score_range_and_neutral(self, n):
        idx = _dates(n)
        reg = pd.Series(Regime.G, index=idx)
        half = pd.Series(0.5, index=idx)
        df = sc.total_score(Sector.POWER, reg, half, half, half)
        assert (df["score"] == 50.0).all()
        assert set(df.columns) >= {"score", "trend", "volume", "macro"}


class TestSignals:
    def test_thresholds_and_confirmation(self):
        idx = _dates(8)
        # 70 하루로는 전환 X (확인 2일), 이틀 연속이면 LONG
        score = pd.Series([30, 30, 70, 30, 70, 70, 50, 50], index=idx, dtype=float)
        out = sg.signal_series(score)
        assert out["stance"].iloc[0] == Stance.CASH.value
        assert out["stance"].iloc[3] == Stance.CASH.value  # 1일 스파이크 무시
        assert out["stance"].iloc[5] == Stance.LONG.value  # 2일 연속 → 전환
        assert out["signal"].iloc[6] == Signal.KEEP.value  # 중간 구간 = 유지

    def test_cooldown_asymmetry(self):
        idx = _dates(12)
        # LONG 진입 직후 급락 — 방어 방향 쿨다운 3일이라 charge 가능
        score = pd.Series([70, 70, 70, 35, 35, 35, 35, 70, 70, 70, 70, 70], index=idx, dtype=float)
        cfg = SignalConfig()
        out = sg.signal_series(score, cfg)
        assert out["stance"].iloc[0] == Stance.LONG.value
        # 3~4일차 (전환 후 3일 경과 + 2일 확인) → CASH 전환 발생
        assert Stance.CASH.value in set(out["stance"].iloc[3:7])
        # CASH → LONG 재진입은 쿨다운 5일 후에만
        cash_idx = list(out["stance"]).index(Stance.CASH.value)
        relong = out["stance"].iloc[cash_idx:].eq(Stance.LONG.value)
        if relong.any():
            first_relong = relong.idxmax()
            assert (out.index.get_loc(first_relong) - cash_idx) >= 5

    def test_transitions_and_immediate_flag(self):
        idx = _dates(6)
        stance = pd.Series(["LONG", "LONG", "CASH", "CASH", "LONG", "LONG"], index=idx)
        tr = sg.stance_transitions(stance)
        assert len(tr) == 2
        assert bool(tr["immediate"].iloc[0]) is True    # LONG→CASH 즉시
        assert bool(tr["immediate"].iloc[1]) is False   # CASH→LONG 다이제스트

    def test_reason_template(self):
        reason = sg.build_reason(
            "반도체", "보유", "현금보유", "긴축 스트레스 국면", True,
            {"trend": 0.71, "volume": 0.60, "macro": 0.55},
            {"trend": 0.38, "volume": 0.55, "macro": 0.30},
        )
        assert "반도체: 보유→현금보유" in reason
        assert "긴축 스트레스 국면 진입" in reason
        assert "추세" in reason


class TestNewsFilter:
    def test_single_article_spike_filtered(self):
        idx = _dates(60)
        sent = pd.Series(0.0, index=idx)
        cnt = pd.Series(0.0, index=idx)
        sent.iloc[-1] = 0.9  # 기사 1건짜리 스파이크
        cnt.iloc[-1] = 1
        out = news_signal(sent, cnt)
        assert bool(out["passed"].iloc[-1]) is False
        assert out["news_score"].iloc[-1] == 0.5

    def test_broad_persistent_negative_passes(self):
        idx = _dates(90)
        rng = np.random.default_rng(1)
        sent = pd.Series(0.05 * rng.standard_normal(90), index=idx)
        cnt = pd.Series(3.0, index=idx)
        sent.iloc[-5:] = -0.7  # 5일 연속 강한 부정
        cnt.iloc[-5:] = 8
        out = news_signal(sent, cnt)
        assert bool(out["passed"].iloc[-1]) is True
        assert out["news_score"].iloc[-1] < 0.4

    def test_geopolitical_boost(self):
        idx = _dates(10)
        cnt = pd.Series([0, 0, 0, 1, 2, 3, 6, 0, 0, 0], index=idx, dtype=float)
        boost = geopolitical_boost(cnt)
        assert boost.iloc[6] == 0.10
        assert boost.iloc[0] == 0.0
