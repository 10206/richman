"""신호 상태기계 (docs/02 §4) — 임계값 + 히스테리시스 + 확인 + 쿨다운.

내부 스탠스: LONG / CASH. 표시 신호: hold(보유) / cash(현금보유) / keep(유지).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class Stance(str, Enum):
    LONG = "LONG"
    CASH = "CASH"


class Signal(str, Enum):
    HOLD = "hold"    # 🟢▲ 보유
    CASH = "cash"    # 🔴■ 현금보유
    KEEP = "keep"    # 🟡▶ 유지


SIGNAL_LABELS_KO = {Signal.HOLD: "보유", Signal.CASH: "현금보유", Signal.KEEP: "유지"}


@dataclass(frozen=True)
class SignalConfig:
    """기본 임계값 55/35는 2015~2026 백테스트 그리드 서치로 확정 (docs/04 §4).

    초안(65/40)은 중립적 시장에서 과도하게 현금 대기 → 상승분 손실이 컸음.
    '기본은 보유, 명백히 나쁠 때만 현금'이 목적에 부합.
    """

    enter_long: float = 55.0   # 이상이면 LONG (docs/02 §4)
    enter_cash: float = 35.0   # 이하이면 CASH
    confirm_days: int = 2      # 연속 확인일
    cooldown_to_long: int = 5  # CASH→LONG 최소 간격 (거래일)
    cooldown_to_cash: int = 3  # LONG→CASH 최소 간격 (방어는 빠르게)


DEFAULT_CONFIG = SignalConfig()


def signal_series(score: pd.Series, cfg: SignalConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    """점수 시계열 → (stance, signal) 시계열.

    초기 스탠스는 첫 유효 점수 기준 (50 이상 LONG, 미만 CASH).
    반환 컬럼: stance, signal
    """
    values = score.to_numpy(dtype=float)
    n = len(values)
    stances: list[str] = [""] * n
    signals: list[str] = [""] * n

    stance: Stance | None = None
    pending: Stance | None = None
    pending_run = 0
    days_since_flip = 10**9

    for i in range(n):
        v = values[i]
        if np.isnan(v):
            stances[i] = stance.value if stance else Stance.CASH.value
            signals[i] = Signal.KEEP.value
            days_since_flip += 1
            continue
        if stance is None:
            stance = Stance.LONG if v >= 50 else Stance.CASH
            stances[i] = stance.value
            signals[i] = Signal.HOLD.value if stance is Stance.LONG else Signal.CASH.value
            continue

        days_since_flip += 1
        candidate: Stance | None = None
        if v >= cfg.enter_long:
            candidate = Stance.LONG
        elif v <= cfg.enter_cash:
            candidate = Stance.CASH

        signal = Signal.KEEP
        if candidate is not None and candidate != stance:
            pending_run = pending_run + 1 if pending == candidate else 1
            pending = candidate
            cooldown = cfg.cooldown_to_long if candidate is Stance.LONG else cfg.cooldown_to_cash
            if pending_run >= cfg.confirm_days and days_since_flip >= cooldown:
                stance = candidate
                pending, pending_run = None, 0
                days_since_flip = 0
        else:
            pending, pending_run = None, 0

        if candidate == stance:
            # 임계값을 계속 충족 중이면 명시적 신호 유지 (보유/현금보유 재확인)
            signal = Signal.HOLD if stance is Stance.LONG else Signal.CASH
        stances[i] = stance.value
        signals[i] = signal.value

    return pd.DataFrame({"stance": stances, "signal": signals}, index=score.index)


def stance_transitions(stance: pd.Series) -> pd.DataFrame:
    """스탠스 전환 이벤트 추출 → 알림 대상 (docs/02 §4 표).

    반환 컬럼: from_stance, to_stance, immediate (LONG→CASH만 True)
    """
    prev = stance.shift(1)
    flips = stance[(stance != prev) & prev.notna()]
    return pd.DataFrame(
        {
            "from_stance": prev.loc[flips.index],
            "to_stance": flips,
            "immediate": [
                str(f) == Stance.CASH.value for f in flips
            ],
        },
        index=flips.index,
    )


def build_reason(
    sector_label: str,
    from_signal: str,
    to_signal: str,
    regime_label: str,
    regime_changed: bool,
    components_prev: dict[str, float],
    components_now: dict[str, float],
) -> str:
    """알림 한 줄 이유 — 규칙 기반 (LLM 없음, docs/02 §4).

    컴포넌트 변화가 가장 큰 항목 + 국면 전환 여부로 구성.
    """
    names = {"trend": "추세", "volume": "거래량", "macro": "거시"}
    deltas = {
        k: components_now.get(k, 0.5) - components_prev.get(k, 0.5)
        for k in names
    }
    key = max(deltas, key=lambda k: abs(deltas[k]))
    direction = "급락" if deltas[key] < -0.15 else ("하락" if deltas[key] < 0 else ("급등" if deltas[key] > 0.15 else "상승"))
    parts = []
    if regime_changed:
        parts.append(f"{regime_label} 진입")
    parts.append(f"{names[key]} 점수 {direction}"
                 f" ({components_prev.get(key, 0.5):.2f}→{components_now.get(key, 0.5):.2f})")
    return f"{sector_label}: {from_signal}→{to_signal} (" + " + ".join(parts) + ")"
