"""FRED 미국 거시 시계열 수집.

설계 근거:
  - FRED_API_KEY가 있으면 공식 API(json) 사용 — 안정적 + 리비전 메타데이터.
  - 키가 없으면 market.fetch_fred_csv(fredgraph CSV, 키 불필요) 폴백.
    백테스트(P3)에서 이미 검증된 경로라 프로덕션 폴백으로 안전.
  - 반환은 항상 pd.Series (DatetimeIndex, NaN 제거) — 엔진 입력 규격.
"""

from __future__ import annotations

import httpx
import pandas as pd

from app.data.market import fetch_fred_csv

_API_URL = "https://api.stlouisfed.org/fred/series/observations"


def get_series(
    series_id: str,
    start: str = "2014-01-01",
    api_key: str | None = None,
    timeout: float = 30.0,
) -> pd.Series:
    """FRED 시리즈 1개 → pd.Series (DatetimeIndex, float, NaN 제거).

    api_key가 None이면 fredgraph CSV 폴백 (키 불필요).
    """
    if api_key:
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start,
        }
        resp = httpx.get(_API_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        if not obs:
            raise ValueError(f"FRED: no observations for {series_id!r}")
        s = pd.Series(
            [pd.to_numeric(o["value"], errors="coerce") for o in obs],
            index=pd.to_datetime([o["date"] for o in obs]),
            name=series_id,
            dtype=float,
        )
    else:
        df = fetch_fred_csv([series_id], timeout=timeout)
        s = df[series_id]
    s = s.dropna().sort_index()
    s.index.name = "date"
    return s.loc[start:]


def get_many(
    series_ids: list[str],
    start: str = "2014-01-01",
    api_key: str | None = None,
) -> pd.DataFrame:
    """여러 시리즈를 outer join한 DataFrame (컬럼 = series_id)."""
    frames = [get_series(sid, start=start, api_key=api_key) for sid in series_ids]
    return pd.concat(frames, axis=1, join="outer").sort_index()
