"""이달의 경제 캘린더 — 미국/한국 실적(earnings) + 거시 지표 발표 일정.

정확도 정책:
  - 미국 실적: Alpha Vantage EARNINGS_CALENDAR (실제 확정 발표일, confirmed=True).
  - 거시 지표: FRED/ECOS 릴리스 캘린더 API 키가 없으면, 지표별 정례 주기(cadence)로
    추정한 발표일을 제공한다 (confirmed=False, 앱에서 "예상"으로 표기).
    FRED_API_KEY(미국)/ECOS(한국) 연결 시 확정 일자로 업그레이드 가능.
"""

from __future__ import annotations

import calendar as _cal
import csv
import io
from datetime import date

import httpx

from app.engine.sectors import Sector

_AV_URL = "https://www.alphavantage.co/query"


# ---- 날짜 유틸 ----

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date | None:
    """그 달의 n번째 특정 요일(weekday: 월=0..일=6). 없으면 None."""
    count = 0
    for day in range(1, _cal.monthrange(year, month)[1] + 1):
        d = date(year, month, day)
        if d.weekday() == weekday:
            count += 1
            if count == n:
                return d
    return None


def _last_weekday(year: int, month: int, weekday: int) -> date | None:
    for day in range(_cal.monthrange(year, month)[1], 0, -1):
        d = date(year, month, day)
        if d.weekday() == weekday:
            return d
    return None


def _clamp_day(year: int, month: int, day: int) -> date:
    last = _cal.monthrange(year, month)[1]
    return date(year, month, min(day, last))


# ---- 거시 지표 정례 주기 규칙 ----
# rule(year, month) -> date | None
_MON, _TUE, _WED, _THU, _FRI = 0, 1, 2, 3, 4

# 발표시간(현지 표준시)은 각 지표의 관례적 공표 시각 — 서머타임/공휴일에 따라 소폭 달라질 수 있음.
_MACRO_RULES = [
    # (market, title, importance, release_time, rule)  importance: 3=최상 2=상 1=중
    ("US", "고용보고서(비농업 고용)", 3, "08:30 ET", lambda y, m: _nth_weekday(y, m, _FRI, 1)),
    ("US", "소비자물가(CPI)", 3, "08:30 ET", lambda y, m: _nth_weekday(y, m, _WED, 2)),
    ("US", "생산자물가(PPI)", 2, "08:30 ET", lambda y, m: _nth_weekday(y, m, _THU, 2)),
    ("US", "소매판매", 2, "08:30 ET", lambda y, m: _nth_weekday(y, m, _TUE, 3)),
    ("US", "개인소비지출(PCE) 물가", 2, "08:30 ET", lambda y, m: _last_weekday(y, m, _FRI)),
    ("US", "ISM 제조업 PMI", 1, "10:00 ET", lambda y, m: _clamp_day(y, m, 1)),
    ("KR", "수출입동향(관세청)", 2, "09:00 KST", lambda y, m: _clamp_day(y, m, 1)),
    ("KR", "소비자물가동향(통계청)", 3, "08:00 KST", lambda y, m: _nth_weekday(y, m, _TUE, 1)),
]

# 분기 지표 (해당 분기 첫 달에 전분기치 발표)
_QUARTERLY = [
    ("US", "GDP(속보치)", 2, "08:30 ET", {1: 30, 4: 30, 7: 30, 10: 30}),
    ("KR", "GDP(속보치, 한국은행)", 2, "08:00 KST", {1: 25, 4: 25, 7: 25, 10: 25}),
]

# 통화정책 회의 (2026 예정, 결정일 기준 — 확정 일자는 각 중앙은행 공지 확인 권장)
_FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
              "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16"]
_BOK_2026 = ["2026-01-15", "2026-02-26", "2026-04-09", "2026-05-28",
             "2026-07-09", "2026-08-27", "2026-10-15", "2026-11-26"]


def macro_events(year: int, month: int) -> list[dict]:
    """해당 월의 거시 지표 발표 예상 일정 (confirmed=False).

    result/actual/estimate는 컨센서스+실제치 소스(예: FMP)가 연결되면 채워진다. 현재는 None.
    """
    events: list[dict] = []

    def add(market: str, title: str, importance: int, release_time: str | None, d: date | None):
        if d is not None and d.year == year and d.month == month:
            events.append({
                "date": d.isoformat(), "market": market, "category": "macro",
                "title": title, "importance": importance, "confirmed": False,
                "release_time": release_time, "result": None,
            })

    for market, title, imp, rtime, rule in _MACRO_RULES:
        add(market, title, imp, rtime, rule(year, month))

    for market, title, imp, rtime, month_day in _QUARTERLY:
        if month in month_day:
            add(market, title, imp, rtime, _clamp_day(year, month, month_day[month]))

    for iso in _FOMC_2026:
        add("US", "FOMC 정책금리 결정", 3, "14:00 ET", date.fromisoformat(iso))
    for iso in _BOK_2026:
        add("KR", "한국은행 금통위 정책금리 결정", 3, "09:00 KST", date.fromisoformat(iso))

    return events


# ---- 미국 실적 캘린더 (Alpha Vantage) ----
# 섹터 대표 종목 (실적 발표 필터). 국채는 개별 실적 없음.
_WATCH: dict[Sector, list[str]] = {
    Sector.SEMICONDUCTOR: ["NVDA", "AMD", "INTC", "TSM", "MU", "AVGO", "QCOM", "TXN"],
    Sector.ROBOTICS: ["ISRG", "ROK", "TER", "ABB", "ZBRA"],
    Sector.POWER: ["NEE", "DUK", "SO", "VST", "GEV", "ETN"],
    Sector.HEALTHCARE: ["UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO"],
    Sector.GOLD: ["NEM", "GOLD", "AEM", "FNV"],
}
_TICKER_SECTOR: dict[str, Sector] = {t: s for s, ts in _WATCH.items() for t in ts}


def earnings_events(year: int, month: int, api_key: str | None, timeout: float = 30.0) -> list[dict]:
    """해당 월의 미국 관심 종목 실적 발표 (Alpha Vantage, confirmed=True). 키 없으면 빈 목록."""
    if not api_key:
        return []
    params = {"function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": api_key}
    resp = httpx.get(_AV_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    text = resp.text.strip()
    if not text.startswith("symbol"):
        raise RuntimeError(f"Alpha Vantage EARNINGS_CALENDAR 응답 오류: {text[:120]}")

    events: list[dict] = []
    for row in csv.DictReader(io.StringIO(text)):
        sym = (row.get("symbol") or "").strip()
        sector = _TICKER_SECTOR.get(sym)
        if sector is None:
            continue
        rd = (row.get("reportDate") or "").strip()
        try:
            d = date.fromisoformat(rd)
        except ValueError:
            continue
        if d.year != year or d.month != month:
            continue
        name = (row.get("name") or sym).strip().title()
        tod = (row.get("timeOfTheDay") or "").strip().lower()
        release_time = {"bmo": "장 시작 전", "amc": "장 마감 후"}.get(tod)
        events.append({
            "date": d.isoformat(), "market": "US", "category": "earnings",
            "title": f"{name} ({sym}) 실적", "sector": sector.value,
            "importance": 2, "confirmed": True,
            "release_time": release_time, "result": None,
        })
    return events


def month_calendar(year: int, month: int, av_key: str | None) -> list[dict]:
    """거시 + 실적 통합, 날짜·중요도 순 정렬."""
    events = macro_events(year, month)
    try:
        events += earnings_events(year, month, av_key)
    except Exception:  # noqa: BLE001 — 실적 실패해도 거시 캘린더는 제공
        pass
    events.sort(key=lambda e: (e["date"], -e["importance"]))
    return events
