"""일일 배치 파이프라인 — 시세/거시 수집 → 엔진 계산 → 저장 → 알림 이벤트.

사용법:
  python -m app.jobs.daily_pipeline --market US            # 오늘자 갱신
  python -m app.jobs.daily_pipeline --market KR --days 1200
  python -m app.jobs.daily_pipeline --market US --backfill # 과거 이력 일괄 저장

설계 근거:
  - 신호/점수 계산은 engine.pipeline(백테스트와 동일 코드 경로)만 사용 — LLM 0회.
  - 일부 섹터의 데이터 수집이 실패해도 나머지 섹터는 계속 진행 (개인용 도구라
    부분 성공이 전체 실패보다 낫다). 실패는 로그 + 결과 요약에 기록.
  - KR 금리: ECOS 키 없으면 미국 금리(DGS2/DGS10)로 대체하고 macro_snapshots에
    "degraded": true 기록 (가정 A7 — 글로벌 축은 원래 미국 지표 기준이라
    방향성은 유지되지만 L축 정확도가 떨어짐을 명시).
  - 백필은 z-score 워밍업 구간(초기 252거래일)을 제외하고 저장 — 백테스트(P3)의
    평가 구간과 동일 기준.
  - 뉴스 요약(Claude Haiku)은 표시용 부가 기능: anthropic 지연 import,
    키 없으면 조용히 스킵, 실패해도 파이프라인은 성공 처리.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from datetime import datetime, timedelta

import pandas as pd

from app.config import Settings, get_settings
from app.data import ecos, fred, news, prices
from app.db.store import Store, get_store
from app.engine import news_filter as nf
from app.engine import signals as sg
from app.engine.pipeline import MacroInputs, MarketState, compute_market_state, compute_sector_frame
from app.engine.sectors import REGIME_LABELS_KO, SECTOR_LABELS_KO, Market, Regime, Sector

logger = logging.getLogger(__name__)

FRED_US_SERIES = ["DGS2", "DGS10", "DFII10", "VIXCLS", "BAMLH0A0HYM2", "DTWEXBGS"]
WARMUP_ROWS = 252          # 백필 시 제외할 z-score 워밍업 구간 (거래일)
NEWS_LOOKBACK_DAYS = 30    # 뉴스 감성 상대 창 (가장 최신 기사 기준 N일 이내)
NEWS_REQUEST_INTERVAL_SEC = 1.5   # AV 무료 티어 초당 1회 버스트 제한 회피
STANCE_LABELS = {"LONG": "보유", "CASH": "현금보유"}
HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _f(v) -> float | None:
    """NaN → None (JSON/SQLite 저장용)."""
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(fv) else round(fv, 4)


# ------------------------------------------------------------
# 수집
# ------------------------------------------------------------


def collect_prices(
    market: Market, start: str, settings: Settings
) -> tuple[dict[Sector, pd.DataFrame], pd.DataFrame, list[str]]:
    """섹터 6개 + 벤치마크 시세. 실패 섹터는 스킵하고 계속 진행."""
    kis_client = None
    if market == Market.KR and settings.kis_app_key and settings.kis_app_secret:
        from app.data.kis import KISClient

        kis_client = KISClient(settings.kis_app_key, settings.kis_app_secret)

    sector_px: dict[Sector, pd.DataFrame] = {}
    failures: list[str] = []
    for sector in Sector:
        try:
            px = prices.get_sector_prices(market, sector, start, kis_client=kis_client)
            if len(px) < 60:
                raise ValueError(f"데이터 부족 ({len(px)}일)")
            sector_px[sector] = px
        except Exception as e:  # noqa: BLE001 — 섹터 단위 격리
            logger.warning("[%s] %s 시세 수집 실패: %s — 섹터 스킵", market.value, sector.value, e)
            failures.append(f"{sector.value}: {e}")

    benchmark = prices.get_benchmark_prices(market, start)  # 벤치마크 실패는 치명적 → 전파
    return sector_px, benchmark, failures


def collect_macro(
    market: Market, start: str, settings: Settings, benchmark: pd.DataFrame
) -> tuple[MacroInputs, dict]:
    """거시 시계열 수집 → MacroInputs + 스냅샷 메타(degraded 등)."""
    meta: dict = {"degraded": False, "sources": {}}
    fkey = settings.fred_api_key

    # 글로벌 공통 (가정 A7): VIX/HY 스프레드는 KR도 FRED 사용
    vix = fred.get_series("VIXCLS", start, api_key=fkey)
    hy = fred.get_series("BAMLH0A0HYM2", start, api_key=fkey)
    real_rate = fred.get_series("DFII10", start, api_key=fkey)
    dollar = fred.get_series("DTWEXBGS", start, api_key=fkey)
    meta["sources"]["risk"] = "FRED(VIXCLS,BAMLH0A0HYM2)"

    if market == Market.US:
        y_short = fred.get_series("DGS2", start, api_key=fkey)
        y_long = fred.get_series("DGS10", start, api_key=fkey)
        meta["sources"]["rates"] = "FRED(DGS2,DGS10)"
    else:
        end = datetime.now().strftime("%Y-%m-%d")
        try:
            y_short = ecos.get_ktb_3y(settings.ecos_api_key, start, end)
            y_long = ecos.get_ktb_10y(settings.ecos_api_key, start, end)
            meta["sources"]["rates"] = "ECOS(817Y002: 국고3Y/10Y)"
        except Exception as e:  # noqa: BLE001 — 키 없음(ValueError)/API 장애 모두 대체 경로로
            # ECOS 키 없음/장애 → 미국 금리로 대체 (방향성 근사) + degraded 표시
            logger.warning("[KR] ECOS 금리 수집 실패 (%s) → 미국 금리 대체 (degraded)", e)
            y_short = fred.get_series("DGS2", start, api_key=fkey)
            y_long = fred.get_series("DGS10", start, api_key=fkey)
            meta["degraded"] = True
            meta["sources"]["rates"] = "FRED(DGS2,DGS10) — ECOS 대체 (degraded)"

    macro = MacroInputs(
        benchmark_close=benchmark["close"],
        vix=vix,
        hy_spread=hy,
        y_short=y_short,
        y_long=y_long,
        real_rate=real_rate,
        dollar_index=dollar,
    )
    return macro, meta


def collect_news(
    market: Market, settings: Settings
) -> tuple[dict[Sector, list[dict]], dict[Sector, pd.Series], pd.Series | None, dict]:
    """뉴스 감성 수집 → (원본 기사, 필터 통과 감성 시계열, 지정학 보정, 메타).

    - US: Alpha Vantage (키 없으면 전부 비어있음 → 파이프라인은 중립 처리)
    - KR: KR-FinBert-SC 스텁 (NEWS_KR_ENABLED 기본 꺼짐)
    """
    articles: dict[Sector, list[dict]] = {}
    sentiment: dict[Sector, pd.Series] = {}
    geo_boost: pd.Series | None = None
    meta: dict = {"news": {}}

    if market == Market.KR:
        for sector in Sector:
            items = news.fetch_kr_news(sector, enabled=settings.news_kr_enabled)
            if items:
                articles[sector] = items
        return articles, sentiment, geo_boost, meta

    if not settings.alphavantage_api_key:
        return articles, sentiment, geo_boost, meta

    # 서버 시계 기준 절대 창(time_from) 대신 "가장 최신 기사 기준 상대 창"을 쓴다.
    # AV 무료 티어의 최신 기사 날짜가 서버 시계보다 뒤처져 있어도(간극) 견고하게 최신 뉴스를 확보.
    # AV 무료 티어는 초당 1회 버스트 제한이 있어 섹터 요청 사이에 간격을 둔다 (일당 25회는 6요청이라 여유).
    for i, sector in enumerate(Sector):
        if i > 0:
            time.sleep(NEWS_REQUEST_INTERVAL_SEC)
        try:
            items = news.fetch_us_news(sector, settings.alphavantage_api_key)
        except Exception as e:  # noqa: BLE001 — 뉴스는 부가 신호, 실패해도 계속
            logger.warning("[US] %s 뉴스 수집 실패: %s", sector.value, e)
            continue
        if not items:
            continue
        items.sort(key=lambda it: it.get("date", ""), reverse=True)
        newest = datetime.strptime(items[0]["date"], "%Y-%m-%d")
        cutoff = (newest - timedelta(days=NEWS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        items = [it for it in items if it.get("date", "") >= cutoff]
        articles[sector] = items
        daily = news.daily_sentiment(items)
        if len(daily) >= 3:
            sig = nf.news_signal(daily["sentiment"], daily["article_count"])
            sentiment[sector] = sig["news_score"]
            meta["news"][sector.value] = {
                "news_score": _f(sig["news_score"].iloc[-1]),
                "news_z": _f(sig["z"].iloc[-1]),
                "articles_3d": _f(daily["article_count"].tail(3).sum()),
            }
        if sector == Sector.GOLD:
            geo = news.geopolitical_article_count(items)
            if len(geo):
                geo_boost = nf.geopolitical_boost(geo)
    return articles, sentiment, geo_boost, meta


# ------------------------------------------------------------
# 저장/알림
# ------------------------------------------------------------


def frame_to_rows(frame: pd.DataFrame, market: Market, sector: Sector) -> list[dict]:
    rows = []
    for dt, r in frame.iterrows():
        rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "market": market.value,
                "sector": sector.value,
                "score": _f(r["score"]),
                "trend": _f(r["trend"]),
                "volume": _f(r["volume"]),
                "macro": _f(r["macro"]),
                "w_trend": _f(r["w_trend"]),
                "w_volume": _f(r["w_volume"]),
                "w_macro": _f(r["w_macro"]),
                "signal": r["signal"],
                "stance": r["stance"],
                "regime": str(r["regime"]),
            }
        )
    return rows


def state_to_rows(state: MarketState, market: Market) -> list[dict]:
    df = pd.DataFrame(
        {
            "regime": state.regime,
            "r_score": state.r_score.reindex(state.regime.index),
            "l_score": state.l_score.reindex(state.regime.index),
            "local_trend": state.local_trend.reindex(state.regime.index),
        }
    ).dropna(subset=["regime"])
    return [
        {
            "date": dt.strftime("%Y-%m-%d"),
            "market": market.value,
            "regime": str(r["regime"]),
            "r_score": _f(r["r_score"]),
            "l_score": _f(r["l_score"]),
            "local_trend": _f(r["local_trend"]),
        }
        for dt, r in df.iterrows()
    ]


def detect_and_notify(
    store: Store, market: Market, sector: Sector,
    new_row: dict, prev_row: dict | None, regime_changed: bool,
) -> int | None:
    """스탠스 전환 감지 → 알림 이벤트 생성. LONG→CASH만 immediate (docs/02 §4)."""
    if prev_row is None or prev_row["stance"] == new_row["stance"]:
        return None
    from_label = STANCE_LABELS.get(prev_row["stance"], prev_row["stance"])
    to_label = STANCE_LABELS.get(new_row["stance"], new_row["stance"])
    sector_label = SECTOR_LABELS_KO[sector]
    regime_label = REGIME_LABELS_KO[Regime(new_row["regime"])]
    body = sg.build_reason(
        sector_label, from_label, to_label, regime_label, regime_changed,
        {k: prev_row.get(k) or 0.5 for k in ("trend", "volume", "macro")},
        {k: new_row.get(k) or 0.5 for k in ("trend", "volume", "macro")},
    )
    immediate = new_row["stance"] == "CASH"  # LONG→CASH 전환은 즉시 알림
    title = f"[{market.value}] {sector_label} 신호 전환: {from_label} → {to_label}"
    return store.insert_notification(
        market.value, sector.value, "signal_change", title, body, immediate
    )


def summarize_news(
    store: Store, market: Market, articles: dict[Sector, list[dict]],
    as_of: str, settings: Settings,
) -> int:
    """섹터별 뉴스 요약 (Claude Haiku, 한국어 2문장) — 표시용. 키 없으면 스킵.

    신호/점수 계산 경로와 완전히 분리된 부가 기능 (docs/03 §4: 일 12콜 이하).
    """
    if not settings.anthropic_api_key or not articles:
        return 0
    try:
        import anthropic  # 지연 import — 키 없으면 패키지 자체가 불필요
    except ImportError:
        logger.warning("anthropic 패키지 미설치 — 뉴스 요약 스킵 (pip install anthropic)")
        return 0

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    count = 0
    for sector, items in articles.items():
        titles = [f"- {it['title']} ({it['date']})" for it in items[:12] if it.get("title")]
        if not titles:
            continue
        try:
            resp = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=300,
                system=(
                    "너는 개인 투자자를 위한 금융 뉴스 요약 도우미다. "
                    "주어진 최근 뉴스 헤드라인을 바탕으로 해당 섹터의 분위기를 "
                    "한국어 2문장으로 요약하라. 과장 없이 사실 위주로."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"섹터: {SECTOR_LABELS_KO[sector]} ({market.value})\n"
                            f"최근 헤드라인:\n" + "\n".join(titles)
                        ),
                    }
                ],
            )
            text = next((b.text for b in resp.content if b.type == "text"), "").strip()
            if text:
                store.upsert_news_summary(as_of, market.value, sector.value, text)
                count += 1
        except Exception as e:  # noqa: BLE001 — 요약 실패는 파이프라인 실패가 아님
            logger.warning("[%s] %s 뉴스 요약 실패: %s", market.value, sector.value, e)
    return count


# ------------------------------------------------------------
# 메인
# ------------------------------------------------------------


def run_pipeline(
    market: Market,
    days: int = 1200,
    backfill: bool = False,
    settings: Settings | None = None,
    store: Store | None = None,
) -> dict:
    """파이프라인 1회 실행. 결과 요약 dict 반환 (API /jobs/run에서도 사용)."""
    settings = settings or get_settings()
    store = store or get_store(settings)
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    summary: dict = {"market": market.value, "start": start, "backfill": backfill}

    # 1) 시세
    sector_px, benchmark, price_failures = collect_prices(market, start, settings)
    summary["price_failures"] = price_failures
    if not sector_px:
        raise RuntimeError(f"[{market.value}] 모든 섹터 시세 수집 실패 — 중단")

    # 2) 거시
    macro, macro_meta = collect_macro(market, start, settings, benchmark)

    # 3) 뉴스 감성 (키 있으면)
    articles, news_sent, geo_boost, news_meta = collect_news(market, settings)
    macro.news_sentiment = news_sent
    macro.geopolitical_boost = geo_boost

    # 4) 엔진 계산 (전체 시계열)
    state = compute_market_state(macro)
    frames: dict[Sector, pd.DataFrame] = {}
    engine_failures: list[str] = []
    for sector, px in sector_px.items():
        try:
            frames[sector] = compute_sector_frame(sector, px, state, macro)
        except Exception as e:  # noqa: BLE001 — 섹터 단위 격리
            logger.warning("[%s] %s 점수 계산 실패: %s", market.value, sector.value, e)
            engine_failures.append(f"{sector.value}: {e}")
    summary["engine_failures"] = engine_failures
    if not frames:
        raise RuntimeError(f"[{market.value}] 모든 섹터 점수 계산 실패 — 중단")

    as_of = max(f.index[-1] for f in frames.values()).strftime("%Y-%m-%d")
    summary["as_of"] = as_of

    # 5) 알림 감지는 upsert 전에 (직전 "저장된" 신호와 비교)
    regime_rows = state_to_rows(state, market)
    prev_regime = store.get_latest_regime(market.value)
    latest_regime_row = regime_rows[-1] if regime_rows else None
    regime_changed = bool(
        prev_regime and latest_regime_row
        and prev_regime["date"] < latest_regime_row["date"]
        and prev_regime["regime"] != latest_regime_row["regime"]
    )

    notifications = 0
    score_rows_all: list[dict] = []
    latest_rows: dict[Sector, dict] = {}
    for sector, frame in frames.items():
        rows = frame_to_rows(frame, market, sector)
        if backfill:
            rows = rows[WARMUP_ROWS:] if len(rows) > WARMUP_ROWS else rows[-1:]
        else:
            rows = rows[-1:]
        if not rows:
            continue
        new_row = rows[-1]
        latest_rows[sector] = new_row
        prev_row = store.get_score_before(market.value, sector.value, new_row["date"])
        if prev_row is None and len(rows) >= 2:
            prev_row = rows[-2]  # 최초 실행(백필)이면 계산된 직전 행과 비교
        if detect_and_notify(store, market, sector, new_row, prev_row, regime_changed):
            notifications += 1
        score_rows_all.extend(rows)

    # 국면 전환 이벤트 (다이제스트 — immediate=False)
    if regime_changed and latest_regime_row:
        old_label = REGIME_LABELS_KO[Regime(prev_regime["regime"])]
        new_label = REGIME_LABELS_KO[Regime(latest_regime_row["regime"])]
        store.insert_notification(
            market.value, None, "regime_change",
            f"[{market.value}] 거시 국면 전환: {old_label} → {new_label}",
            f"R점수 {latest_regime_row['r_score']}, L점수 {latest_regime_row['l_score']} "
            f"({prev_regime['regime']} → {latest_regime_row['regime']})",
            False,
        )
        notifications += 1

    # 6) 저장 (daily_scores / regime_history / macro_snapshots)
    store.upsert_daily_scores(score_rows_all)
    if backfill:
        keep = regime_rows[WARMUP_ROWS:] if len(regime_rows) > WARMUP_ROWS else regime_rows[-1:]
        store.upsert_regime_history(keep)
    elif regime_rows:
        store.upsert_regime_history(regime_rows[-1:])

    idx = macro.benchmark_close.index

    def _last(s: pd.Series | None):
        if s is None or s.empty:
            return None
        return _f(s.reindex(idx.union(s.index)).ffill().reindex(idx).iloc[-1])

    payload = {
        "y_short": _last(macro.y_short),
        "y_long": _last(macro.y_long),
        "y_long_chg_63d": _last(macro.y_long.diff(63)),
        "vix": _last(macro.vix),
        "hy_spread": _last(macro.hy_spread),
        "real_rate": _last(macro.real_rate),
        "dollar_index": _last(macro.dollar_index),
        **macro_meta,
        **news_meta,
    }
    store.upsert_macro_snapshot(as_of, market.value, payload)

    # 7) 뉴스 원본 저장 + 요약 (표시용)
    news_rows = [
        {**{k: it.get(k) for k in ("date", "title", "url", "source", "sentiment")},
         "market": market.value, "sector": sector.value}
        for sector, items in articles.items()
        for it in items
    ]
    if news_rows:
        store.insert_news_items(news_rows)
    summaries = summarize_news(store, market, articles, as_of, settings)

    summary.update(
        {
            "sectors_saved": sorted(s.value for s in latest_rows),
            "rows_upserted": len(score_rows_all),
            "notifications": notifications,
            "news_items": len(news_rows),
            "news_summaries": summaries,
            "degraded": macro_meta.get("degraded", False),
            "signals": {
                s.value: {"score": r["score"], "signal": r["signal"], "stance": r["stance"]}
                for s, r in latest_rows.items()
            },
        }
    )
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="일일 매매신호 배치 파이프라인")
    ap.add_argument("--market", required=True, choices=["US", "KR"])
    ap.add_argument("--days", type=int, default=1200, help="수집 기간 (달력일, 기본 1200)")
    ap.add_argument("--backfill", action="store_true", help="과거 이력 전체를 일괄 upsert")
    args = ap.parse_args()

    result = run_pipeline(Market(args.market), days=args.days, backfill=args.backfill)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
