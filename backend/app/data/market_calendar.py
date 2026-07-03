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
import logging
from datetime import date

import httpx

from app.engine.sectors import Sector

logger = logging.getLogger(__name__)

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


# 미국 거시 지표 → FRED (릴리스ID, 데이터 시리즈, units, 헤드라인 포맷).
# 확정 발표일(release_id) + 실제 발표값(series/units)을 함께 붙인다.
_FRED_INDICATOR: dict[str, tuple[int, str, str, "callable"]] = {
    "고용보고서(비농업 고용)": (50, "PAYEMS", "chg", lambda v: f"비농업 {v:+.0f}K"),
    "소비자물가(CPI)": (10, "CPIAUCSL", "pc1", lambda v: f"전년비 {v:+.1f}%"),
    "생산자물가(PPI)": (46, "PPIFIS", "pc1", lambda v: f"전년비 {v:+.1f}%"),
    "소매판매": (9, "RSAFS", "pch", lambda v: f"전월비 {v:+.1f}%"),
    "개인소비지출(PCE) 물가": (54, "PCEPI", "pc1", lambda v: f"전년비 {v:+.1f}%"),
    "GDP(속보치)": (53, "A191RL1Q225SBEA", "lin", lambda v: f"연율 {v:+.1f}%"),
}
_FRED_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"
_FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"

# ForexFactory(FairEconomy) 무료 주간 캘린더 — 컨센서스(forecast) 제공. 비공식·이번 주만.
_FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_FF_TITLE_MAP = {
    "Non-Farm Employment Change": "고용보고서(비농업 고용)",
    "ISM Manufacturing PMI": "ISM 제조업 PMI",
    "CPI m/m": "소비자물가(CPI)",
    "PPI m/m": "생산자물가(PPI)",
    "Retail Sales m/m": "소매판매",
    "Core PCE Price Index m/m": "개인소비지출(PCE) 물가",
    "Advance GDP q/q": "GDP(속보치)",
    "Federal Funds Rate": "FOMC 정책금리 결정",
}


def _ff_num(s: str | None) -> float | None:
    """'114K','7.28M','-0.1%','4.3%' → 앞쪽 숫자(부호 포함). 접미사/부호 처리."""
    if not s:
        return None
    import re
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)", s.replace(",", ""))
    return float(m.group(1)) if m else None


def _macro_result(actual: str, forecast: str) -> str | None:
    """실제 vs 컨센서스 → 상회/부합/하회 (같은 소스·같은 단위 전제)."""
    a, f = _ff_num(actual), _ff_num(forecast)
    if a is None or f is None:
        return None
    if abs(a - f) < 1e-9:
        return "meet"
    return "beat" if a > f else "miss"


def forexfactory_consensus(timeout: float = 20.0) -> dict[str, dict]:
    """이번 주 미국 지표의 {지표명: {forecast, actual, date}} (컨센서스)."""
    resp = httpx.get(_FF_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    resp.raise_for_status()
    out: dict[str, dict] = {}
    for e in resp.json():
        if e.get("country") != "USD":
            continue
        ind = _FF_TITLE_MAP.get((e.get("title") or "").strip())
        if not ind:
            continue
        out[ind] = {
            "forecast": (e.get("forecast") or "").strip(),
            "actual": (e.get("actual") or "").strip(),
            "date": (e.get("date") or "")[:10],
        }
    return out


def _fred_release_dates(release_id: int, api_key: str, released_only: bool = False,
                        timeout: float = 15.0) -> list[str]:
    """릴리스 발표일 목록(desc). released_only=True면 실제 데이터가 나온 발표일만."""
    resp = httpx.get(_FRED_DATES_URL, params={
        "release_id": release_id, "api_key": api_key, "file_type": "json",
        "include_release_dates_with_no_data": "false" if released_only else "true",
        "sort_order": "desc", "limit": 24,
    }, timeout=timeout)
    resp.raise_for_status()
    return [x.get("date", "") for x in resp.json().get("release_dates", [])]


def _fred_actual(series: str, units: str, asof: str, api_key: str, timeout: float = 15.0) -> float | None:
    """asof 시점에 알려진 최신 관측값(해당 발표로 공개된 값). 없으면 None."""
    resp = httpx.get(_FRED_OBS_URL, params={
        "series_id": series, "api_key": api_key, "file_type": "json", "units": units,
        "realtime_start": asof, "realtime_end": asof, "sort_order": "desc", "limit": 1,
    }, timeout=timeout)
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    if obs and obs[0].get("value") not in (".", "", None):
        try:
            return float(obs[0]["value"])
        except ValueError:
            return None
    return None


def macro_events(year: int, month: int, fred_key: str | None = None,
                 today_iso: str | None = None) -> list[dict]:
    """해당 월의 거시 지표 발표 일정.

    fred_key 있으면 미국 지표(고용/CPI/PPI/소매판매/PCE/GDP)를 FRED 확정 발표일(confirmed=True)로
    업그레이드하고, 이미 발표된 지표엔 실제 발표값(actual)을 채운다. ISM/FOMC/한국은 예상 유지.
    """
    events: list[dict] = []

    def add(market: str, title: str, importance: int, release_time: str | None, d: date | None):
        if d is not None and d.year == year and d.month == month:
            events.append({
                "date": d.isoformat(), "market": market, "category": "macro",
                "title": title, "importance": importance, "confirmed": False,
                "release_time": release_time, "result": None,
                "actual": None, "estimate": None,
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

    if fred_key:
        ym = f"{year:04d}-{month:02d}"
        for e in events:
            cfg = _FRED_INDICATOR.get(e["title"])
            if cfg is None or e["market"] != "US":
                continue
            rid, series, units, fmt = cfg
            try:
                # 1) 확정 발표일 (예정 포함)
                scheduled = _fred_release_dates(rid, fred_key, released_only=False)
                d = next((x for x in scheduled if x[:7] == ym), None)
                if not d:
                    continue
                e["date"] = d
                e["confirmed"] = True
                # 2) 이미 발표된 날이면 실제 발표값
                if today_iso and d <= today_iso:
                    released = set(_fred_release_dates(rid, fred_key, released_only=True))
                    if d in released:
                        v = _fred_actual(series, units, d, fred_key)
                        if v is not None:
                            e["actual"] = fmt(v)
            except Exception:  # noqa: BLE001 — 실패 시 예상일/값없음 유지
                continue

    # ForexFactory 컨센서스(이번 주 미국 지표) → estimate + 상회/부합/하회
    ym = f"{year:04d}-{month:02d}"
    try:
        cons = forexfactory_consensus()
        for e in events:
            if e["market"] != "US" or e["category"] != "macro":
                continue
            c = cons.get(e["title"])
            if not c or c.get("date", "")[:7] != ym:
                continue
            if c.get("forecast"):
                e["estimate"] = c["forecast"]
            if c.get("actual"):
                e["actual"] = c["actual"]                       # FF 실제(컨센서스와 동일 단위)
                r = _macro_result(c["actual"], c["forecast"])
                if r:
                    e["result"] = r
    except Exception:  # noqa: BLE001 — 컨센서스 실패해도 캘린더는 정상
        pass

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
    # 일일 한도 초과 시 헤더만 담긴 짧은 응답이 옴 (정상 CSV는 수십만 바이트)
    if len(text) < 500:
        raise RuntimeError(f"Alpha Vantage EARNINGS_CALENDAR 한도 초과/빈 응답: {text[:120]}")

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
            "title": f"{name} ({sym}) 실적", "sector": sector.value, "ticker": sym,
            "importance": 2, "confirmed": True,
            "release_time": release_time, "result": None, "estimate": None,
        })
    return events


# ---- 실적 서프라이즈 (Financial Modeling Prep, 무료 티어의 종목별 실적) ----
_FMP_BASE = "https://financialmodelingprep.com/stable"


def _fmp_earnings_result(symbol: str, report_date: str, api_key: str, timeout: float = 20.0) -> str | None:
    """해당 종목의 report_date 실적 발표치 vs 예상치 → 'beat'|'meet'|'miss'|None(미발표)."""
    resp = httpx.get(f"{_FMP_BASE}/earnings",
                     params={"symbol": symbol, "apikey": api_key}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return None
    for row in data:
        if row.get("date") != report_date:
            continue
        act, est = row.get("epsActual"), row.get("epsEstimated")
        if act is None or est is None:
            return None
        tol = 0.005  # EPS 반올림 오차 — 이보다 크면 상회/하회, 이내면 부합
        if act > est + tol:
            return "beat"
        if act < est - tol:
            return "miss"
        return "meet"
    return None


def enrich_earnings_results(events: list[dict], fmp_key: str | None, today_iso: str) -> None:
    """이미 발표일이 지난 실적 이벤트에 예상치 대비 결과(result)를 채운다 (제자리 수정)."""
    if not fmp_key:
        return
    for e in events:
        if e.get("category") != "earnings" or not e.get("ticker"):
            continue
        if e["date"] > today_iso:   # 아직 발표 전
            continue
        try:
            r = _fmp_earnings_result(e["ticker"], e["date"], fmp_key)
            if r:
                e["result"] = r
        except Exception:  # noqa: BLE001 — 개별 실패는 무시, 나머지 계속
            continue


def month_calendar(year: int, month: int, av_key: str | None,
                   fmp_key: str | None = None, fred_key: str | None = None,
                   today_iso: str | None = None) -> tuple[list[dict], bool]:
    """거시 + 실적 통합, 날짜·중요도 순 정렬.

    fred_key 있으면 미국 거시 지표를 확정 발표일로 업그레이드.
    fmp_key 있으면 발표된 실적에 상회/부합/하회 채움.
    반환: (events, degraded). degraded=True면 실적 수집 실패(한도 등) — 호출측은 캐시하지 말 것.
    """
    events = macro_events(year, month, fred_key=fred_key, today_iso=today_iso)
    degraded = False
    if av_key:
        try:
            earnings = earnings_events(year, month, av_key)
            if today_iso:
                enrich_earnings_results(earnings, fmp_key, today_iso)
            events += earnings
        except Exception as e:  # noqa: BLE001 — 실적 실패해도 거시 캘린더는 제공
            logger.warning("[calendar] 실적 수집 실패 (%s-%02d): %r", year, month, e)
            degraded = True
    events.sort(key=lambda e: (e["date"], -e["importance"]))
    return events, degraded
