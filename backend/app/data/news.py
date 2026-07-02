"""뉴스 감성 수집 — 미국: Alpha Vantage NEWS_SENTIMENT (가정 A6), 한국: 스텁.

설계 근거:
  - Alpha Vantage는 기사별 감성 점수 + 티커 관련성(relevance)을 이미 제공하므로
    별도 모델 호스팅 없이 LLM 0회로 일간 섹터 감성을 만들 수 있다 (docs/03 §3).
  - 섹터→검색 파라미터: ETF 티커는 AV 커버리지가 불안정해서 섹터 대표
    개별 종목 묶음(tickers) + 보조 topics 로 매핑. 관련성 가중 평균으로
    일간 감성 s_t ∈ [-1,1] 과 기사 수를 만든다. 실제 신호 반영 여부는
    engine.news_filter(폭·강도·지속 3중 게이트)가 결정한다.
  - 키가 없으면 None 반환 → 파이프라인은 뉴스를 중립(0.5) 처리.
  - 무료 25 req/day 제한 → 일 1회 배치, 섹터당 1콜(총 6콜)로 설계.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pandas as pd

from app.engine.sectors import Sector

_AV_URL = "https://www.alphavantage.co/query"

# 섹터 → Alpha Vantage 검색 파라미터.
# tickers: 섹터 대표 대형주 (AV 뉴스 커버리지가 확실한 종목 위주)
# topics: 보조 필터 (tickers와 AND가 아닌 문맥 확장용이라 일부만 지정)
SECTOR_QUERY: dict[Sector, dict[str, str]] = {
    Sector.SEMICONDUCTOR: {"tickers": "NVDA,AMD,INTC,TSM,MU"},
    Sector.ROBOTICS: {"tickers": "ISRG,ROK,TER", "topics": "technology"},
    Sector.POWER: {"tickers": "NEE,DUK,SO,VST"},
    Sector.HEALTHCARE: {"tickers": "UNH,JNJ,LLY,PFE"},
    Sector.GOLD: {"tickers": "GLD,NEM,GOLD"},
    Sector.BONDS: {"tickers": "TLT", "topics": "economy_monetary"},
}

# 지정학 리스크 키워드 (금 전용 보정, docs/03 §3)
GEO_KEYWORDS = (
    "war", "invasion", "sanction", "missile", "airstrike", "strike on",
    "conflict", "geopolit", "nuclear", "attack",
)


def fetch_us_news(
    sector: Sector,
    api_key: str | None,
    time_from: str | None = None,
    limit: int = 1000,
    timeout: float = 30.0,
) -> list[dict] | None:
    """섹터 관련 미국 뉴스 기사 목록. 키 없으면 None.

    time_from: 'YYYYMMDDTHHMM' (예: '20260601T0000'). None이면 AV 기본(최근).
    반환 항목: {date, title, url, source, sentiment, relevance}
      - sentiment: 관련 티커 감성(관련성 최대 티커) 우선, 없으면 전체 감성. [-1,1]
    """
    if not api_key:
        return None

    query = SECTOR_QUERY[sector]
    params: dict[str, str] = {
        "function": "NEWS_SENTIMENT",
        "apikey": api_key,
        "limit": str(limit),
        "sort": "LATEST",
        **query,
    }
    if time_from:
        params["time_from"] = time_from

    resp = httpx.get(_AV_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if "feed" not in body:
        # 쿼터 초과/오류도 200으로 옴: {"Note": ...} 또는 {"Information": ...}
        note = body.get("Note") or body.get("Information") or body.get("Error Message")
        raise RuntimeError(f"Alpha Vantage 응답 오류 ({sector.value}): {note or body}")

    wanted = set(query.get("tickers", "").split(",")) - {""}
    items: list[dict] = []
    for art in body["feed"]:
        try:
            ts = datetime.strptime(art["time_published"][:8], "%Y%m%d")
        except (KeyError, ValueError):
            continue
        sentiment = float(art.get("overall_sentiment_score", 0.0))
        relevance = 0.5
        # 관련성이 가장 높은 대상 티커의 감성을 우선 사용
        best = None
        for t in art.get("ticker_sentiment", []):
            if t.get("ticker") in wanted:
                rel = float(t.get("relevance_score", 0.0))
                if best is None or rel > best[0]:
                    best = (rel, float(t.get("ticker_sentiment_score", sentiment)))
        if best is not None:
            relevance, sentiment = best
        items.append(
            {
                "date": ts.strftime("%Y-%m-%d"),
                "title": art.get("title", ""),
                "url": art.get("url", ""),
                "source": art.get("source", ""),
                "sentiment": max(-1.0, min(1.0, sentiment)),
                "relevance": relevance,
            }
        )
    return items


def daily_sentiment(items: list[dict]) -> pd.DataFrame:
    """기사 목록 → 일간 (sentiment [-1,1] 관련성 가중, article_count) 시계열.

    docs/03 §3: s_t = Σ(기사 감성 × 관련성) / Σ(관련성)
    """
    if not items:
        return pd.DataFrame(columns=["sentiment", "article_count"])
    df = pd.DataFrame(items)
    df["date"] = pd.to_datetime(df["date"])
    df["w"] = df["relevance"].clip(lower=0.05)  # 관련성 0 기사도 폭 계산엔 포함
    df["ws"] = df["sentiment"] * df["w"]
    g = df.groupby("date")
    out = pd.DataFrame(
        {
            "sentiment": g["ws"].sum() / g["w"].sum(),
            "article_count": g.size().astype(float),
        }
    ).sort_index()
    out.index.name = "date"
    return out


def geopolitical_article_count(items: list[dict]) -> pd.Series:
    """제목 키워드 매칭 기사 수 (일간) — 금 지정학 보정 입력 (docs/03 §3)."""
    if not items:
        return pd.Series(dtype=float)
    df = pd.DataFrame(items)
    df["date"] = pd.to_datetime(df["date"])
    hit = df["title"].str.lower().apply(lambda t: any(k in t for k in GEO_KEYWORDS))
    s = df[hit].groupby("date").size().astype(float)
    s.index.name = "date"
    return s


def fetch_kr_news(sector: Sector, enabled: bool = False) -> list[dict] | None:
    """한국 뉴스 감성 — KR-FinBert-SC 통합 지점 (스텁).

    향후 통합 계획 (가정 A1, docs/03 §1):
      1. 네이버 금융 섹터 뉴스 크롤링 (일 1회 배치)
      2. HuggingFace `snunlp/KR-FinBert-SC`로 기사별 감성 분류
         (긍정/부정/중립 확률 → [-1,1] 스코어 변환)
      3. fetch_us_news와 동일한 {date,title,url,source,sentiment,relevance}
         스키마로 반환 → daily_sentiment/news_filter 경로 그대로 재사용

    NEWS_KR_ENABLED(기본 false)가 켜지기 전까지는 None을 반환하고
    파이프라인은 한국 뉴스 감성을 중립(0.5) 처리한다.
    모델 배치 실행에는 ~1.5GB 메모리가 필요하므로 Railway 워커 사양 확인 필요.
    """
    if not enabled:
        return None
    raise NotImplementedError(
        "KR-FinBert-SC 통합은 아직 구현되지 않음 — NEWS_KR_ENABLED를 끄거나 "
        "app/data/news.py의 fetch_kr_news를 구현하세요."
    )
