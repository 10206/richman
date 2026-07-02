"""섹터 정의 — ETF 매핑, 국면 반응 bias, 가중치 (docs/01 §4, docs/02 §2).

티커 매핑은 가정 A4 기반이며 여기서만 바꾸면 전체에 반영된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Sector(str, Enum):
    SEMICONDUCTOR = "semiconductor"
    ROBOTICS = "robotics"
    POWER = "power"
    HEALTHCARE = "healthcare"
    GOLD = "gold"
    BONDS = "bonds"


class Market(str, Enum):
    KR = "KR"
    US = "US"


class Regime(str, Enum):
    G = "G"  # Goldilocks: 위험선호 + 금리하락
    R = "R"  # Reflation: 위험선호 + 금리상승
    T = "T"  # Tightening: 위험회피 + 금리상승
    F = "F"  # Flight to safety: 위험회피 + 금리하락


REGIME_LABELS_KO = {
    Regime.G: "이상적 성장 국면",
    Regime.R: "경기 과열 국면",
    Regime.T: "긴축 스트레스 국면",
    Regime.F: "위험회피(안전자산) 국면",
}

SECTOR_LABELS_KO = {
    Sector.SEMICONDUCTOR: "반도체",
    Sector.ROBOTICS: "로봇",
    Sector.POWER: "전력",
    Sector.HEALTHCARE: "헬스케어",
    Sector.GOLD: "금",
    Sector.BONDS: "국채",
}

# docs/01 §4 — 국면 → 섹터 방향 bias (-2 ~ +2)
# 초안에서 2015~2026 백테스트로 보정된 값 (docs/04 §3):
#  - 전력/헬스케어 T: -1 → 0 (방어섹터는 긴축 국면에서 실증적으로 선방 — 2022 XLU 보합)
#  - 반도체/로봇 F: -1 → 0 (F는 확인 시점이 늦어 국면 확정 후엔 반등 구간이 대부분)
#  - 국채 F: +2 → +1 (유동성 위기형 F에서는 장기채도 동반 매도 — 2020.3 실증)
REGIME_BIAS: dict[Sector, dict[Regime, int]] = {
    Sector.SEMICONDUCTOR: {Regime.G: +2, Regime.R: +1, Regime.T: -2, Regime.F: 0},
    Sector.ROBOTICS:      {Regime.G: +2, Regime.R: +1, Regime.T: -2, Regime.F: 0},
    Sector.POWER:         {Regime.G: +1, Regime.R: +1, Regime.T: 0,  Regime.F: +1},
    Sector.HEALTHCARE:    {Regime.G: +1, Regime.R: 0,  Regime.T: 0,  Regime.F: +1},
    Sector.GOLD:          {Regime.G: +1, Regime.R: -1, Regime.T: 0,  Regime.F: +2},
    Sector.BONDS:         {Regime.G: +2, Regime.R: -2, Regime.T: -1, Regime.F: +1},
}

EQUITY_SECTORS = {Sector.SEMICONDUCTOR, Sector.ROBOTICS, Sector.POWER, Sector.HEALTHCARE}
# 성장(고금리민감) 섹터 — rate_sensitivity 전체 강도 적용 대상
GROWTH_SECTORS = {Sector.SEMICONDUCTOR, Sector.ROBOTICS}


@dataclass(frozen=True)
class Weights:
    trend: float
    volume: float
    macro: float


# docs/02 §2 — 기본 가중치
BASE_WEIGHTS: dict[Sector, Weights] = {
    Sector.SEMICONDUCTOR: Weights(0.45, 0.25, 0.30),
    Sector.ROBOTICS:      Weights(0.45, 0.25, 0.30),
    Sector.POWER:         Weights(0.45, 0.25, 0.30),
    Sector.HEALTHCARE:    Weights(0.45, 0.25, 0.30),
    Sector.GOLD:          Weights(0.30, 0.10, 0.60),
    Sector.BONDS:         Weights(0.25, 0.10, 0.65),
}

# 위험회피 국면(T, F)에서 주식 섹터의 가중치 조정
RISK_OFF_EQUITY_WEIGHTS = Weights(0.35, 0.20, 0.45)
RISK_ON_EQUITY_WEIGHTS = Weights(0.50, 0.25, 0.25)


def weights_for(sector: Sector, regime: Regime) -> Weights:
    if sector in EQUITY_SECTORS:
        if regime in (Regime.T, Regime.F):
            return RISK_OFF_EQUITY_WEIGHTS
        return RISK_ON_EQUITY_WEIGHTS
    return BASE_WEIGHTS[sector]


# 컴포넌트 속도 (docs/02 §1, 백테스트 확정 docs/04 §4)
SECTOR_SPEED: dict[Sector, str] = {
    Sector.SEMICONDUCTOR: "fast",
    Sector.ROBOTICS: "fast",
    Sector.POWER: "slow",
    Sector.HEALTHCARE: "slow",
    Sector.GOLD: "slow",
    Sector.BONDS: "slow",
}

# 섹터별 신호 임계값/확인일 (백테스트 그리드 서치로 확정, docs/04 §4)
# (enter_long, enter_cash, confirm_days)
SECTOR_SIGNAL_PARAMS: dict[Sector, tuple[float, float, int]] = {
    Sector.SEMICONDUCTOR: (55.0, 35.0, 2),
    Sector.ROBOTICS:      (55.0, 35.0, 2),
    Sector.POWER:         (50.0, 30.0, 3),  # 방어 섹터: 극단에서만 현금 전환
    Sector.HEALTHCARE:    (50.0, 30.0, 3),
    Sector.GOLD:          (55.0, 35.0, 3),
    Sector.BONDS:         (50.0, 35.0, 3),
}

# 섹터 프록시 (가정 A4). KR 전력은 지수 코드 폴백 — 사용자 확정 필요 (docs/07)
SECTOR_PROXIES: dict[Market, dict[Sector, str]] = {
    Market.KR: {
        Sector.SEMICONDUCTOR: "091160",  # KODEX 반도체
        Sector.ROBOTICS: "445290",       # KODEX K-로봇액티브
        Sector.POWER: "117460",          # KRX 전기가스업 지수 폴백 대신 임시 — docs/07 확인 항목
        Sector.HEALTHCARE: "143860",     # TIGER 헬스케어
        Sector.GOLD: "411060",           # ACE KRX금현물
        Sector.BONDS: "148070",          # KOSEF 국고채10년
    },
    Market.US: {
        Sector.SEMICONDUCTOR: "SMH",
        Sector.ROBOTICS: "BOTZ",
        Sector.POWER: "XLU",
        Sector.HEALTHCARE: "XLV",
        Sector.GOLD: "GLD",
        Sector.BONDS: "TLT",
    },
}
