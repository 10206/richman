"""프레임워크 백테스트 (docs/04) — 미국 데이터 (가정 A5).

사용법:
  .venv/bin/python backtest/run_backtest.py            # 캐시 사용, 리포트 출력
  .venv/bin/python backtest/run_backtest.py --refresh  # 데이터 재다운로드
  .venv/bin/python backtest/run_backtest.py --sensitivity  # 임계값 민감도 분석

검증 내용:
  1) 국면 시계열이 알려진 역사(2020.3 F, 2021 R, 2022 T, 2023H2 G)와 정합하는지
  2) 국면별 섹터 평균 수익률이 bias 부호와 일치하는지
  3) 신호 전략 vs 매수후보유: CAGR / MDD / 전환 횟수
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.market import fetch_fred_csv, fetch_yahoo_daily
from app.engine import signals as sg
from app.engine.pipeline import MacroInputs, compute_market_state, compute_sector_frame, signal_config_for
from app.engine.sectors import REGIME_BIAS, Regime, Sector
from app.engine.signals import SignalConfig, Stance

CACHE = Path(__file__).parent / "cache"
START = "2014-01-01"

ETFS = {
    Sector.SEMICONDUCTOR: "SMH",
    Sector.ROBOTICS: "BOTZ",
    Sector.POWER: "XLU",
    Sector.HEALTHCARE: "XLV",
    Sector.GOLD: "GLD",
    Sector.BONDS: "TLT",
}
FRED_SERIES = ["DGS2", "DGS10", "DFII10", "VIXCLS", "BAMLH0A0HYM2", "DTWEXBGS"]


def load_data(refresh: bool = False) -> tuple[dict[Sector, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    CACHE.mkdir(exist_ok=True)
    prices: dict[Sector, pd.DataFrame] = {}
    for sector, symbol in ETFS.items():
        f = CACHE / f"{symbol.replace('^', '_')}.csv"
        if refresh or not f.exists():
            df = fetch_yahoo_daily(symbol, START)
            df.to_csv(f)
        prices[sector] = pd.read_csv(f, parse_dates=["date"], index_col="date").loc[START:]

    f = CACHE / "spx.csv"
    if refresh or not f.exists():
        fetch_yahoo_daily("^GSPC", START).to_csv(f)
    spx = pd.read_csv(f, parse_dates=["date"], index_col="date").loc[START:]

    f = CACHE / "fred.csv"
    if refresh or not f.exists():
        fetch_fred_csv(FRED_SERIES).to_csv(f)
    fred = pd.read_csv(f, parse_dates=["date"], index_col="date").loc[START:]
    return prices, spx, fred


def compute_us_pipeline(prices, spx, fred):
    """공용 파이프라인(engine/pipeline.py) 그대로 사용 — 프로덕션과 동일 코드 경로."""
    macro = MacroInputs(
        benchmark_close=spx["close"],
        vix=fred["VIXCLS"].dropna(),
        hy_spread=fred["BAMLH0A0HYM2"].dropna(),
        y_short=fred["DGS2"].dropna(),
        y_long=fred["DGS10"].dropna(),
        real_rate=fred["DFII10"].dropna(),
        dollar_index=fred["DTWEXBGS"].dropna(),
    )
    state = compute_market_state(macro)
    results = {}
    for sector, px in prices.items():
        frame = compute_sector_frame(sector, px, state, macro)
        results[sector] = {"px": px.loc[frame.index[0]:], "scores": frame}
    return state.regime, results


def evaluate_strategy(px: pd.DataFrame, scores: pd.DataFrame, cfg: SignalConfig | None = None):
    # cfg=None이면 scores에 이미 포함된 섹터별 기본 신호(stance/signal) 사용
    """신호 전략 성과: 신호는 당일 종가 계산 → 다음날 수익률부터 적용 (룩어헤드 방지)."""
    warmup = 252  # z-score 워밍업 구간은 평가 제외
    score = scores["score"].iloc[warmup:]
    px = px.iloc[warmup:]
    sig = sg.signal_series(score, cfg) if cfg is not None else scores[["stance", "signal"]].iloc[warmup:]
    ret = px["close"].pct_change().fillna(0.0)
    exposure = (sig["stance"] == Stance.LONG.value).astype(float).shift(1).fillna(0.0)
    cost = exposure.diff().abs().fillna(0.0) * 0.001  # 전환당 10bp 거래비용
    strat_ret = ret * exposure - cost

    def stats(r: pd.Series) -> dict:
        curve = (1 + r).cumprod()
        years = len(r) / 252
        cagr = curve.iloc[-1] ** (1 / years) - 1 if years > 0 else 0.0
        mdd = (curve / curve.cummax() - 1).min()
        vol = r.std() * np.sqrt(252)
        sharpe = (r.mean() * 252) / vol if vol > 0 else 0.0
        return {"cagr": cagr, "mdd": mdd, "sharpe": sharpe}

    flips = sg.stance_transitions(sig["stance"])
    s_strat, s_bh = stats(strat_ret), stats(ret)
    return {
        "strat": s_strat,
        "bh": s_bh,
        "n_flips": len(flips),
        "flips_per_year": len(flips) / (len(ret) / 252),
        "time_in_market": exposure.mean(),
    }


def regime_sanity_check(regime: pd.Series) -> pd.DataFrame:
    """알려진 역사적 국면과 비교 — 해당 기간의 최빈 국면."""
    known = [
        ("2020-03-01", "2020-04-15", "F", "코로나 패닉"),
        ("2021-02-01", "2021-11-30", "R", "리플레이션"),
        ("2022-02-01", "2022-10-31", "T", "연준 긴축"),
        ("2023-11-01", "2024-06-30", "G", "AI 랠리+금리 정점"),
    ]
    rows = []
    for start, end, expected, label in known:
        window = regime.loc[start:end]
        if len(window) == 0:
            continue
        counts = window.value_counts(normalize=True)
        top = str(counts.index[0])
        rows.append({
            "기간": f"{start[:7]}~{end[:7]}", "설명": label, "기대": expected,
            "판정(최빈)": top, "비중": f"{counts.iloc[0]:.0%}", "일치": "O" if top == expected else "X",
        })
    return pd.DataFrame(rows)


def regime_return_check(regime: pd.Series, results: dict) -> pd.DataFrame:
    """국면별 섹터 연환산 수익률과 bias 부호의 정합성."""
    rows = []
    for sector, data in results.items():
        ret = data["px"]["close"].pct_change()
        reg = regime.reindex(ret.index).ffill()
        for r in [Regime.G, Regime.R, Regime.T, Regime.F]:
            mask = reg.astype(str) == r.value
            if mask.sum() < 60:
                continue
            ann = ret[mask].mean() * 252
            bias = REGIME_BIAS[sector][r]
            rows.append({
                "sector": sector.value, "regime": r.value, "bias": bias,
                "ann_ret": f"{ann:+.1%}", "days": int(mask.sum()),
                "sign_match": "O" if (ann >= 0) == (bias >= 0) else "X",
            })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--sensitivity", action="store_true")
    args = ap.parse_args()

    prices, spx, fred = load_data(args.refresh)
    for sector, px in prices.items():
        print(f"  {sector.value:15s} {px.index[0].date()} ~ {px.index[-1].date()}  ({len(px)}일)")
    regime, results = compute_us_pipeline(prices, spx, fred)

    print("\n=== 1. 국면 정합성 (알려진 역사) ===")
    print(regime_sanity_check(regime).to_string(index=False))

    print("\n=== 국면 분포 (2015~) ===")
    print(regime.loc["2015":].value_counts(normalize=True).map(lambda x: f"{x:.0%}").to_string())

    print("\n=== 2. 국면별 섹터 수익률 vs bias ===")
    df = regime_return_check(regime, results)
    print(df.to_string(index=False))
    match_rate = (df["sign_match"] == "O").mean()
    print(f"부호 일치율: {match_rate:.0%}")

    print("\n=== 3. 신호 전략 성과 (섹터별 확정 파라미터) ===")
    rows = []
    for sector, data in results.items():
        ev = evaluate_strategy(data["px"], data["scores"])
        rows.append({
            "sector": sector.value,
            "strat_cagr": f"{ev['strat']['cagr']:+.1%}", "bh_cagr": f"{ev['bh']['cagr']:+.1%}",
            "strat_mdd": f"{ev['strat']['mdd']:.1%}", "bh_mdd": f"{ev['bh']['mdd']:.1%}",
            "sharpe": f"{ev['strat']['sharpe']:.2f}", "bh_sharpe": f"{ev['bh']['sharpe']:.2f}",
            "flips/yr": f"{ev['flips_per_year']:.1f}", "in_mkt": f"{ev['time_in_market']:.0%}",
        })
    print(pd.DataFrame(rows).to_string(index=False))

    if args.sensitivity:
        print("\n=== 4. 임계값 민감도 (반도체/국채/금 평균 Sharpe, MDD) ===")
        for enter, exit_ in [(60, 35), (65, 40), (70, 45), (65, 45), (60, 40)]:
            cfg = SignalConfig(enter_long=enter, enter_cash=exit_)
            sh, mdd, fl = [], [], []
            for sector in [Sector.SEMICONDUCTOR, Sector.BONDS, Sector.GOLD, Sector.HEALTHCARE]:
                ev = evaluate_strategy(results[sector]["px"], results[sector]["scores"], cfg)
                sh.append(ev["strat"]["sharpe"]); mdd.append(ev["strat"]["mdd"]); fl.append(ev["flips_per_year"])
            print(f"  enter={enter} exit={exit_}: Sharpe={np.mean(sh):.2f}  MDD={np.mean(mdd):.1%}  flips/yr={np.mean(fl):.1f}")


if __name__ == "__main__":
    main()
