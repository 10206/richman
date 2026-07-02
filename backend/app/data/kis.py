"""KIS Developers (한국투자증권 OpenAPI) 클라이언트 — 일봉 시세.

설계 근거 (가정 A1):
  - 기존 KATT의 KIS 연동 코드에 이 환경에서 접근 불가 → 공식 스펙 기반 신규 작성.
    이 파일 하나에 격리했으므로 기존 코드가 있으면 이 파일만 교체하면 된다.
  - oauth2 토큰(POST /oauth2/tokenP)은 24시간 유효 + 발급 횟수 제한이 있어
    파일(.kis_token.json)에 캐시한다.
  - 국내주식 기간별시세: GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
    (TR: FHKST03010100, 1회 최대 ~100건 → 날짜 구간을 뒤로 이동하며 페이징)
  - 해외주식 기간별시세: GET /uapi/overseas-price/v1/quotations/dailyprice
    (TR: HHDFS76240000, BYMD 기준 과거 방향 페이징)
  - 실계좌 키가 없어 실검증 불가 — 공식 문서 스펙에 충실하게 작성하고
    오류 시 원인을 알 수 있는 메시지를 남긴다. (검증 결과는 AGENT_NOTES.md)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd

BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_CACHE = Path(".kis_token.json")

TR_DOMESTIC_DAILY = "FHKST03010100"
TR_OVERSEAS_DAILY = "HHDFS76240000"

# 해외 거래소 코드 (해외주식 시세용)
EXCHANGE_CODES = {"NAS": "NAS", "NYS": "NYS", "AMS": "AMS"}


class KISClient:
    """KIS OpenAPI 최소 클라이언트 (일봉 조회 전용)."""

    def __init__(
        self,
        app_key: str | None,
        app_secret: str | None,
        base_url: str = BASE_URL,
        token_cache: Path = TOKEN_CACHE,
        timeout: float = 15.0,
    ) -> None:
        if not app_key or not app_secret:
            raise ValueError(
                "KIS_APP_KEY / KIS_APP_SECRET이 설정되지 않음 — KIS 시세를 사용할 수 없습니다. "
                "yfinance 폴백을 사용하거나 https://apiportal.koreainvestment.com 에서 키를 발급하세요."
            )
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = base_url
        self.token_cache = token_cache
        self.timeout = timeout
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # ---------- 토큰 ----------

    def get_token(self) -> str:
        """접근토큰. 파일 캐시(24시간) → 만료 시에만 재발급 (발급 횟수 제한 대응)."""
        now = time.time()
        if self._token and now < self._token_expiry - 300:
            return self._token

        if self.token_cache.exists():
            try:
                cached = json.loads(self.token_cache.read_text())
                if now < cached.get("expiry", 0) - 300:
                    self._token = cached["token"]
                    self._token_expiry = cached["expiry"]
                    return self._token
            except (json.JSONDecodeError, KeyError):
                pass  # 캐시 깨짐 → 재발급

        resp = httpx.post(
            f"{self.base_url}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            },
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"KIS 토큰 발급 실패 [{resp.status_code}]: {resp.text[:300]}")
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise RuntimeError(f"KIS 토큰 응답에 access_token 없음: {body}")
        expires_in = int(body.get("expires_in", 86400))
        self._token = token
        self._token_expiry = now + expires_in
        try:
            self.token_cache.write_text(
                json.dumps({"token": token, "expiry": self._token_expiry})
            )
        except OSError:
            pass  # 캐시 실패는 치명적이지 않음
        return token

    def _headers(self, tr_id: str) -> dict[str, str]:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.get_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",  # 개인
        }

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        resp = httpx.get(
            f"{self.base_url}{path}",
            headers=self._headers(tr_id),
            params=params,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"KIS API 오류 [{resp.status_code}] {path} (TR={tr_id}): {resp.text[:300]}"
            )
        body = resp.json()
        if body.get("rt_cd") not in (None, "0"):
            raise RuntimeError(
                f"KIS 응답 오류 (TR={tr_id}) rt_cd={body.get('rt_cd')} "
                f"msg_cd={body.get('msg_cd')} msg={body.get('msg1')}"
            )
        return body

    # ---------- 국내주식 일봉 ----------

    def fetch_domestic_daily(self, code: str, start: str, end: str | None = None) -> pd.DataFrame:
        """국내주식/ETF 일봉 (수정주가). 컬럼: close, volume (DatetimeIndex).

        code: 6자리 종목코드 (예: '091160'). 1회 최대 ~100건이라
        가장 오래된 반환일 이전으로 조회 구간을 옮겨가며 페이징한다.
        """
        end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        rows: list[dict] = []

        while end_dt >= start_dt:
            body = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                TR_DOMESTIC_DAILY,
                {
                    "FID_COND_MRKT_DIV_CODE": "J",     # 주식/ETF/ETN
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": start_dt.strftime("%Y%m%d"),
                    "FID_INPUT_DATE_2": end_dt.strftime("%Y%m%d"),
                    "FID_PERIOD_DIV_CODE": "D",        # 일봉
                    "FID_ORG_ADJ_PRC": "0",            # 0=수정주가
                },
            )
            chunk = [r for r in body.get("output2", []) if r.get("stck_bsop_date")]
            if not chunk:
                break
            rows.extend(chunk)
            oldest = min(r["stck_bsop_date"] for r in chunk)
            oldest_dt = datetime.strptime(oldest, "%Y%m%d")
            if oldest_dt <= start_dt:
                break
            end_dt = oldest_dt - timedelta(days=1)

        if not rows:
            raise ValueError(f"KIS: 국내 일봉 데이터 없음 (code={code}, {start}~{end})")

        df = pd.DataFrame(
            {
                "date": pd.to_datetime([r["stck_bsop_date"] for r in rows], format="%Y%m%d"),
                "close": pd.to_numeric([r["stck_clpr"] for r in rows], errors="coerce"),
                "volume": pd.to_numeric([r["acml_vol"] for r in rows], errors="coerce"),
            }
        )
        df = df.dropna().drop_duplicates("date").set_index("date").sort_index()
        return df.loc[start:]

    # ---------- 해외주식 일봉 ----------

    def fetch_overseas_daily(
        self, symbol: str, exchange: str, start: str, end: str | None = None
    ) -> pd.DataFrame:
        """해외주식/ETF 일봉. 컬럼: close, volume (DatetimeIndex).

        exchange: NAS(나스닥) / NYS(뉴욕) / AMS(아멕스).
        BYMD(기준일) 이전 ~100건씩 반환 → 과거 방향으로 페이징.
        """
        if exchange not in EXCHANGE_CODES:
            raise ValueError(f"지원하지 않는 거래소 코드: {exchange!r} (NAS/NYS/AMS)")
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        bymd = (datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()).strftime("%Y%m%d")
        rows: list[dict] = []

        while True:
            body = self._get(
                "/uapi/overseas-price/v1/quotations/dailyprice",
                TR_OVERSEAS_DAILY,
                {
                    "AUTH": "",
                    "EXCD": exchange,
                    "SYMB": symbol,
                    "GUBN": "0",   # 0=일
                    "BYMD": bymd,
                    "MODP": "1",   # 1=수정주가 반영
                },
            )
            chunk = [r for r in body.get("output2", []) if r.get("xymd")]
            if not chunk:
                break
            rows.extend(chunk)
            oldest = min(r["xymd"] for r in chunk)
            oldest_dt = datetime.strptime(oldest, "%Y%m%d")
            if oldest_dt <= start_dt:
                break
            bymd = (oldest_dt - timedelta(days=1)).strftime("%Y%m%d")

        if not rows:
            raise ValueError(f"KIS: 해외 일봉 데이터 없음 ({exchange}:{symbol}, {start}~)")

        df = pd.DataFrame(
            {
                "date": pd.to_datetime([r["xymd"] for r in rows], format="%Y%m%d"),
                "close": pd.to_numeric([r["clos"] for r in rows], errors="coerce"),
                "volume": pd.to_numeric([r["tvol"] for r in rows], errors="coerce"),
            }
        )
        df = df.dropna().drop_duplicates("date").set_index("date").sort_index()
        return df.loc[start:]
