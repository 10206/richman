"""한국은행 ECOS API — 한국 금리 시계열.

설계 근거 (docs/03 §1):
  - 국고채 3년/10년: 통계코드 817Y002 (시장금리, 일별),
    항목 010200000=국고채(3년), 010210000=국고채(10년)
  - 기준금리: 722Y001 / 0101000 (일별)
  - StatisticSearch REST 규격:
    https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/{start_row}/{end_row}
      /{STAT_CODE}/{CYCLE}/{START}/{END}/{ITEM_CODE1}
  - 키가 없으면 ValueError — 호출부(daily_pipeline)가 폴백(미국 금리 대체 +
    degraded 마킹)을 결정한다.
"""

from __future__ import annotations

import httpx
import pandas as pd

_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

# (통계코드, 항목코드) 상수
STAT_MARKET_RATE = "817Y002"   # 시장금리 (일별)
ITEM_KTB_3Y = "010200000"      # 국고채(3년)
ITEM_KTB_10Y = "010210000"     # 국고채(10년)
STAT_BASE_RATE = "722Y001"     # 한국은행 기준금리
ITEM_BASE_RATE = "0101000"

_MAX_ROWS = 10000  # 일별 40년치도 커버 — 단일 요청으로 충분


def _fetch(
    api_key: str,
    stat_code: str,
    item_code: str,
    start: str,
    end: str,
    cycle: str = "D",
    timeout: float = 30.0,
) -> pd.Series:
    """StatisticSearch 1회 호출 → pd.Series (DatetimeIndex, float).

    start/end: 'YYYY-MM-DD' 또는 'YYYYMMDD' (내부에서 YYYYMMDD로 정규화).
    """
    s0 = start.replace("-", "")
    e0 = end.replace("-", "")
    url = f"{_BASE}/{api_key}/json/kr/1/{_MAX_ROWS}/{stat_code}/{cycle}/{s0}/{e0}/{item_code}"
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    # ECOS는 오류도 200으로 반환: {"RESULT": {"CODE": "...", "MESSAGE": "..."}}
    if "RESULT" in payload:
        r = payload["RESULT"]
        raise ValueError(f"ECOS 오류 [{r.get('CODE')}]: {r.get('MESSAGE')}")
    block = payload.get("StatisticSearch")
    if not block or "row" not in block:
        raise ValueError(f"ECOS: 응답에 데이터 없음 (stat={stat_code}, item={item_code})")

    rows = block["row"]
    idx = pd.to_datetime([r["TIME"] for r in rows], format="%Y%m%d")
    values = pd.to_numeric([r["DATA_VALUE"] for r in rows], errors="coerce")
    s = pd.Series(values, index=idx, dtype=float).dropna().sort_index()
    s.index.name = "date"
    return s


def _require_key(api_key: str | None) -> str:
    if not api_key:
        raise ValueError(
            "ECOS_API_KEY가 설정되지 않음 — 한국 금리를 조회할 수 없습니다. "
            "https://ecos.bok.or.kr 에서 무료 키 발급 후 환경변수로 주입하세요."
        )
    return api_key


def get_ktb_3y(api_key: str | None, start: str, end: str) -> pd.Series:
    """국고채 3년 일별 수익률 (%)."""
    return _fetch(_require_key(api_key), STAT_MARKET_RATE, ITEM_KTB_3Y, start, end)


def get_ktb_10y(api_key: str | None, start: str, end: str) -> pd.Series:
    """국고채 10년 일별 수익률 (%)."""
    return _fetch(_require_key(api_key), STAT_MARKET_RATE, ITEM_KTB_10Y, start, end)


def get_base_rate(api_key: str | None, start: str, end: str) -> pd.Series:
    """한국은행 기준금리 (%)."""
    return _fetch(_require_key(api_key), STAT_BASE_RATE, ITEM_BASE_RATE, start, end)
