"""API 라우트 — STATE.md의 API 계약(P4↔P5 공유, 변경 금지) 구현.

설계 근거:
  - 앱(iOS)은 배치가 저장해 둔 결과만 읽는다 — 이 계층에서 계산/LLM 호출 없음.
  - prev_signal/signal_changed/score_delta_1d는 daily_scores의 직전 거래일
    row와 비교해 계산. signal_changed는 스탠스(LONG/CASH) 전환 기준
    (표시 신호 hold/keep 진동은 "변화"가 아님 — 알림 정책과 동일 기준).
  - 스토어는 app.state.store에서 주입받아 테스트에서 교체 가능.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Query, Request

from app.db.store import Store
from app.engine.sectors import (
    REGIME_BIAS,
    REGIME_LABELS_KO,
    SECTOR_LABELS_KO,
    Market,
    Regime,
    Sector,
    sector_basket,
)

router = APIRouter(prefix="/api/v1")


def _local_trend_label(value: float | None) -> str | None:
    """엔진의 로컬 추세 수치(1.0/0.5/0.0)를 API 계약의 문자열로 변환 (iOS가 파싱)."""
    if value is None:
        return None
    if value >= 0.75:
        return "bull"
    if value <= 0.25:
        return "bear"
    return "neutral"


def _store(request: Request) -> Store:
    return request.app.state.store


def _parse_market(market: str) -> Market:
    try:
        return Market(market.upper())
    except ValueError:
        raise HTTPException(status_code=404, detail=f"unknown market: {market}") from None


def _parse_sector(sector: str) -> Sector:
    try:
        return Sector(sector.lower())
    except ValueError:
        raise HTTPException(status_code=404, detail=f"unknown sector: {sector}") from None


def _sector_item(store: Store, row: dict) -> dict:
    """daily_scores row → 대시보드 섹터 항목 (직전 거래일 비교 포함)."""
    prev = store.get_score_before(row["market"], row["sector"], row["date"])
    item = {
        "market": row["market"],
        "sector": row["sector"],
        "label": SECTOR_LABELS_KO[Sector(row["sector"])],
        "score": row["score"],
        "trend": row["trend"],
        "volume": row["volume"],
        "macro": row["macro"],
        "w_trend": row["w_trend"],
        "w_volume": row["w_volume"],
        "w_macro": row["w_macro"],
        "signal": row["signal"],
        "stance": row["stance"],
        "prev_signal": prev["signal"] if prev else None,
        "signal_changed": bool(prev and prev["stance"] != row["stance"]),
        "score_delta_1d": (
            round(row["score"] - prev["score"], 1)
            if prev and prev.get("score") is not None and row.get("score") is not None
            else None
        ),
    }
    return item


@router.get("/dashboard")
def dashboard(request: Request) -> dict:
    store = _store(request)
    markets: dict[str, dict] = {}
    sectors: list[dict] = []
    as_of: str | None = None

    for market in Market:
        regime_row = store.get_latest_regime(market.value)
        if regime_row:
            markets[market.value] = {
                "regime": regime_row["regime"],
                "regime_label": REGIME_LABELS_KO.get(
                    Regime(regime_row["regime"]), regime_row["regime"]
                ),
                "r_score": regime_row["r_score"],
                "l_score": regime_row["l_score"],
                "local_trend": _local_trend_label(regime_row["local_trend"]),
            }
        rows = store.get_latest_scores(market.value)
        for row in rows:
            sectors.append(_sector_item(store, row))
            if as_of is None or row["date"] > as_of:
                as_of = row["date"]

    return {
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "markets": markets,
        "sectors": sectors,
    }


@router.get("/sectors/{market}/{sector}/history")
def sector_history(
    request: Request, market: str, sector: str, days: int = Query(180, ge=1, le=5000)
) -> dict:
    m, s = _parse_market(market), _parse_sector(sector)
    rows = _store(request).get_sector_history(m.value, s.value, days)
    return {
        "items": [
            {
                "date": r["date"],
                "score": r["score"],
                "trend": r["trend"],
                "volume": r["volume"],
                "macro": r["macro"],
                "signal": r["signal"],
                "stance": r["stance"],
                "regime": r["regime"],
            }
            for r in rows
        ]
    }


@router.get("/sectors/{market}/{sector}/detail")
def sector_detail(request: Request, market: str, sector: str) -> dict:
    m, s = _parse_market(market), _parse_sector(sector)
    store = _store(request)

    rows = store.get_latest_scores(m.value)
    row = next((r for r in rows if r["sector"] == s.value), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no data for {m.value}/{s.value}")

    item = _sector_item(store, row)
    regime = Regime(row["regime"]) if row.get("regime") in {r.value for r in Regime} else None
    snapshot = store.get_macro_snapshot(m.value) or {}
    news_meta = (snapshot.get("news") or {}).get(s.value, {})
    macro_raw = {
        "y_short": snapshot.get("y_short"),
        "y_long": snapshot.get("y_long"),
        "y_long_chg_63d": snapshot.get("y_long_chg_63d"),
        "vix": snapshot.get("vix"),
        "hy_spread": snapshot.get("hy_spread"),
        "real_rate": snapshot.get("real_rate"),
        "dollar_index": snapshot.get("dollar_index"),
        "news_score": news_meta.get("news_score"),
        "news_z": news_meta.get("news_z"),
    }
    return {
        "sector": item,
        "regime_bias": REGIME_BIAS[s][regime] if regime else 0,
        "macro_raw": macro_raw,
        "basket": sector_basket(m, s),
        "news_summary": store.get_news_summary(m.value, s.value),
        "news_items": store.get_news_items(m.value, s.value, limit=20),
    }


@router.get("/regime/history")
def regime_history(
    request: Request, market: str = Query("US"), days: int = Query(365, ge=1, le=5000)
) -> dict:
    m = _parse_market(market)
    rows = _store(request).get_regime_history(m.value, days)
    return {
        "items": [
            {
                "date": r["date"],
                "regime": r["regime"],
                "r_score": r["r_score"],
                "l_score": r["l_score"],
                "local_trend": _local_trend_label(r["local_trend"]),
            }
            for r in rows
        ]
    }


@router.get("/notifications/pending")
def notifications_pending(request: Request) -> dict:
    return {"items": _store(request).pending_notifications()}


@router.post("/notifications/ack")
def notifications_ack(request: Request, body: dict = Body(...)) -> dict:
    ids = body.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        raise HTTPException(status_code=422, detail="body must be {\"ids\": [int]}")
    return {"acked": _store(request).ack_notifications(ids)}


# 캘린더 캐시: (year, month, 오늘) → events. AV 실적 호출을 일 1회로 제한.
_calendar_cache: dict[tuple[int, int, str], list[dict]] = {}


@router.get("/calendar")
def calendar_endpoint(request: Request, month: str | None = Query(None),
                      diag: int = Query(0)) -> dict:
    """이달의 경제 캘린더 (미국/한국 실적 + 거시 지표 발표).

    month: "YYYY-MM" (없으면 서버 기준 현재 월). 실적은 AV 확정일, 거시는 정례 주기 예상.
    """
    from app.data import market_calendar as mc

    now = datetime.now(timezone.utc)
    if month:
        try:
            year, mon = int(month[:4]), int(month[5:7])
            assert 1 <= mon <= 12
        except (ValueError, AssertionError):
            raise HTTPException(status_code=422, detail="month은 'YYYY-MM' 형식이어야 함")
    else:
        year, mon = now.year, now.month

    if diag:
        settings = request.app.state.settings
        out: dict = {"av_key_set": bool(settings.alphavantage_api_key),
                     "fmp_key_set": bool(settings.fmp_api_key)}
        try:
            raw = mc.earnings_events(year, mon, settings.alphavantage_api_key)
            out["earnings_count"] = len(raw)
            out["sample"] = [e.get("title") for e in raw[:3]]
        except Exception as e:  # noqa: BLE001
            out["earnings_error"] = repr(e)
        return out

    cache_key = (year, mon, now.date().isoformat())
    events = _calendar_cache.get(cache_key)
    if events is None:
        settings = request.app.state.settings
        events = mc.month_calendar(
            year, mon, settings.alphavantage_api_key,
            fmp_key=settings.fmp_api_key, today_iso=now.date().isoformat(),
        )
        _calendar_cache.clear()  # 하루 전날 캐시 정리
        _calendar_cache[cache_key] = events

    return {"month": f"{year:04d}-{mon:02d}", "events": events}


@router.post("/jobs/run")
def jobs_run(
    request: Request,
    market: str = Query(...),
    days: int = Query(1200, ge=100, le=5000),
    backfill: bool = Query(False),
) -> dict:
    """파이프라인 수동 실행 — API_KEY 설정 필수 (STATE.md: 키 필수)."""
    settings = request.app.state.settings
    if not settings.api_key:
        raise HTTPException(
            status_code=403,
            detail="API_KEY가 설정되지 않아 원격 잡 실행이 비활성화됨 (배치는 CLI로 실행하세요)",
        )
    m = _parse_market(market)
    from app.jobs.daily_pipeline import run_pipeline

    try:
        return run_pipeline(m, days=days, backfill=backfill, settings=settings, store=_store(request))
    except Exception as e:  # noqa: BLE001 — 원인 메시지를 그대로 전달
        raise HTTPException(status_code=500, detail=f"파이프라인 실패: {e}") from e
