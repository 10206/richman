"""저장 계층 — 추상 인터페이스 + SQLite(로컬 기본) + Supabase(프로덕션).

설계 근거 (가정 A9):
  - 로컬 개발/검증은 Supabase 없이 SQLite로 전체 파이프라인이 돌아야 한다.
  - SUPABASE_URL이 설정되면 SupabaseStore 사용 (스키마는 migrations/001_init.sql).
  - 두 구현 모두 dict(list[dict]) 입출력 — API 계약(STATE.md)의 JSON 스키마와
    1:1 대응하도록 컬럼명을 맞춘다.
  - 날짜는 "YYYY-MM-DD" 문자열, 시각은 ISO8601 UTC 문자열로 통일.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCORE_COLUMNS = [
    "date", "market", "sector", "score", "trend", "volume", "macro",
    "w_trend", "w_volume", "w_macro", "signal", "stance", "regime",
]
REGIME_COLUMNS = ["date", "market", "regime", "r_score", "l_score", "local_trend"]


class Store(ABC):
    """저장 계층 추상 인터페이스."""

    # ---- daily_scores ----
    @abstractmethod
    def upsert_daily_scores(self, rows: list[dict]) -> None: ...

    @abstractmethod
    def get_latest_scores(self, market: str) -> list[dict]:
        """해당 시장의 최신 저장일 전체 섹터 row."""

    @abstractmethod
    def get_score_before(self, market: str, sector: str, date: str) -> dict | None:
        """date 이전(<)의 가장 최근 row — 직전 거래일 비교용."""

    @abstractmethod
    def get_sector_history(self, market: str, sector: str, days: int) -> list[dict]:
        """최근 days개 row (날짜 오름차순)."""

    # ---- regime_history ----
    @abstractmethod
    def upsert_regime_history(self, rows: list[dict]) -> None: ...

    @abstractmethod
    def get_latest_regime(self, market: str) -> dict | None: ...

    @abstractmethod
    def get_regime_history(self, market: str, days: int) -> list[dict]: ...

    # ---- macro_snapshots ----
    @abstractmethod
    def upsert_macro_snapshot(self, date: str, market: str, payload: dict) -> None: ...

    @abstractmethod
    def get_macro_snapshot(self, market: str, date: str | None = None) -> dict | None:
        """date=None이면 최신 스냅샷의 payload."""

    # ---- notification_events ----
    @abstractmethod
    def insert_notification(
        self, market: str, sector: str | None, event_type: str,
        title: str, body: str, immediate: bool,
    ) -> int: ...

    @abstractmethod
    def pending_notifications(self) -> list[dict]: ...

    @abstractmethod
    def ack_notifications(self, ids: list[int]) -> int: ...

    # ---- news ----
    @abstractmethod
    def insert_news_items(self, rows: list[dict]) -> None: ...

    @abstractmethod
    def get_news_items(self, market: str, sector: str, limit: int = 20) -> list[dict]: ...

    @abstractmethod
    def upsert_news_summary(self, date: str, market: str, sector: str, summary: str) -> None: ...

    @abstractmethod
    def get_news_summary(self, market: str, sector: str) -> str | None:
        """최신 요약 1건."""


# ============================================================
# SQLite (로컬 기본)
# ============================================================

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_scores (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    sector TEXT NOT NULL,
    score REAL, trend REAL, volume REAL, macro REAL,
    w_trend REAL, w_volume REAL, w_macro REAL,
    signal TEXT, stance TEXT, regime TEXT,
    UNIQUE(date, market, sector)
);
CREATE TABLE IF NOT EXISTS regime_history (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    regime TEXT, r_score REAL, l_score REAL, local_trend REAL,
    UNIQUE(date, market)
);
CREATE TABLE IF NOT EXISTS macro_snapshots (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(date, market)
);
CREATE TABLE IF NOT EXISTS notification_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    market TEXT NOT NULL,
    sector TEXT,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    immediate INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    sector TEXT NOT NULL,
    title TEXT, url TEXT, source TEXT, sentiment REAL,
    UNIQUE(market, sector, url)
);
CREATE TABLE IF NOT EXISTS news_summaries (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    sector TEXT NOT NULL,
    summary TEXT,
    UNIQUE(date, market, sector)
);
"""


class SQLiteStore(Store):
    """로컬 SQLite 구현 — 단일 프로세스(배치 + uvicorn 단일 워커) 가정."""

    def __init__(self, db_path: str = "./richman.db") -> None:
        self.db_path = db_path
        # FastAPI TestClient/uvicorn 스레드에서 공유하기 위해 check_same_thread=False + 락
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SQLITE_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ---- daily_scores ----

    def upsert_daily_scores(self, rows: list[dict]) -> None:
        sql = (
            f"INSERT INTO daily_scores ({', '.join(SCORE_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(SCORE_COLUMNS))}) "
            "ON CONFLICT(date, market, sector) DO UPDATE SET "
            + ", ".join(f"{c}=excluded.{c}" for c in SCORE_COLUMNS[3:])
        )
        with self._lock:
            self._conn.executemany(sql, [tuple(r[c] for c in SCORE_COLUMNS) for r in rows])
            self._conn.commit()

    def get_latest_scores(self, market: str) -> list[dict]:
        return self._query(
            "SELECT * FROM daily_scores WHERE market=? AND "
            "date=(SELECT MAX(date) FROM daily_scores WHERE market=?) ORDER BY sector",
            (market, market),
        )

    def get_score_before(self, market: str, sector: str, date: str) -> dict | None:
        rows = self._query(
            "SELECT * FROM daily_scores WHERE market=? AND sector=? AND date<? "
            "ORDER BY date DESC LIMIT 1",
            (market, sector, date),
        )
        return rows[0] if rows else None

    def get_sector_history(self, market: str, sector: str, days: int) -> list[dict]:
        rows = self._query(
            "SELECT * FROM daily_scores WHERE market=? AND sector=? "
            "ORDER BY date DESC LIMIT ?",
            (market, sector, days),
        )
        return list(reversed(rows))

    # ---- regime_history ----

    def upsert_regime_history(self, rows: list[dict]) -> None:
        sql = (
            f"INSERT INTO regime_history ({', '.join(REGIME_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(REGIME_COLUMNS))}) "
            "ON CONFLICT(date, market) DO UPDATE SET "
            + ", ".join(f"{c}=excluded.{c}" for c in REGIME_COLUMNS[2:])
        )
        with self._lock:
            self._conn.executemany(sql, [tuple(r[c] for c in REGIME_COLUMNS) for r in rows])
            self._conn.commit()

    def get_latest_regime(self, market: str) -> dict | None:
        rows = self._query(
            "SELECT * FROM regime_history WHERE market=? ORDER BY date DESC LIMIT 1",
            (market,),
        )
        return rows[0] if rows else None

    def get_regime_history(self, market: str, days: int) -> list[dict]:
        rows = self._query(
            "SELECT * FROM regime_history WHERE market=? ORDER BY date DESC LIMIT ?",
            (market, days),
        )
        return list(reversed(rows))

    # ---- macro_snapshots ----

    def upsert_macro_snapshot(self, date: str, market: str, payload: dict) -> None:
        self._exec(
            "INSERT INTO macro_snapshots (date, market, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(date, market) DO UPDATE SET payload=excluded.payload",
            (date, market, json.dumps(payload, ensure_ascii=False)),
        )

    def get_macro_snapshot(self, market: str, date: str | None = None) -> dict | None:
        if date:
            rows = self._query(
                "SELECT payload FROM macro_snapshots WHERE market=? AND date=?",
                (market, date),
            )
        else:
            rows = self._query(
                "SELECT payload FROM macro_snapshots WHERE market=? ORDER BY date DESC LIMIT 1",
                (market,),
            )
        return json.loads(rows[0]["payload"]) if rows else None

    # ---- notification_events ----

    def insert_notification(
        self, market: str, sector: str | None, event_type: str,
        title: str, body: str, immediate: bool,
    ) -> int:
        cur = self._exec(
            "INSERT INTO notification_events "
            "(created_at, market, sector, event_type, title, body, immediate, delivered) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (utcnow_iso(), market, sector, event_type, title, body, int(immediate)),
        )
        return int(cur.lastrowid)

    def pending_notifications(self) -> list[dict]:
        rows = self._query(
            "SELECT id, created_at, market, sector, event_type, title, body, immediate "
            "FROM notification_events WHERE delivered=0 ORDER BY id"
        )
        for r in rows:
            r["immediate"] = bool(r["immediate"])
        return rows

    def ack_notifications(self, ids: list[int]) -> int:
        if not ids:
            return 0
        placeholders = ", ".join("?" * len(ids))
        cur = self._exec(
            f"UPDATE notification_events SET delivered=1 WHERE delivered=0 AND id IN ({placeholders})",
            tuple(ids),
        )
        return cur.rowcount

    # ---- news ----

    def insert_news_items(self, rows: list[dict]) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT OR IGNORE INTO news_items (date, market, sector, title, url, source, sentiment) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (r["date"], r["market"], r["sector"], r.get("title"),
                     r.get("url"), r.get("source"), r.get("sentiment"))
                    for r in rows
                ],
            )
            self._conn.commit()

    def get_news_items(self, market: str, sector: str, limit: int = 20) -> list[dict]:
        return self._query(
            "SELECT date, title, url, source, sentiment FROM news_items "
            "WHERE market=? AND sector=? ORDER BY date DESC, id DESC LIMIT ?",
            (market, sector, limit),
        )

    def upsert_news_summary(self, date: str, market: str, sector: str, summary: str) -> None:
        self._exec(
            "INSERT INTO news_summaries (date, market, sector, summary) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(date, market, sector) DO UPDATE SET summary=excluded.summary",
            (date, market, sector, summary),
        )

    def get_news_summary(self, market: str, sector: str) -> str | None:
        rows = self._query(
            "SELECT summary FROM news_summaries WHERE market=? AND sector=? "
            "ORDER BY date DESC LIMIT 1",
            (market, sector),
        )
        return rows[0]["summary"] if rows else None


# ============================================================
# Supabase (프로덕션 — migrations/001_init.sql 스키마 필요)
# ============================================================


class SupabaseStore(Store):
    """Supabase(Postgres) 구현. SUPABASE_URL + SERVICE_KEY 필요.

    supabase-py의 upsert(on_conflict=...)로 SQLite와 동일 시맨틱을 유지한다.
    이 환경에서는 실 Supabase 프로젝트가 없어 통합 테스트는 사용자 배포 후 수행
    (docs/05 가이드 예정). 인터페이스 계약은 tests/test_store.py의 SQLite와 공유.
    """

    def __init__(self, url: str, service_key: str) -> None:
        from supabase import create_client  # 지연 import — 로컬 SQLite 경로에선 불필요

        self.client = create_client(url, service_key)

    # ---- daily_scores ----

    def upsert_daily_scores(self, rows: list[dict]) -> None:
        if rows:
            self.client.table("daily_scores").upsert(
                rows, on_conflict="date,market,sector"
            ).execute()

    def get_latest_scores(self, market: str) -> list[dict]:
        latest = (
            self.client.table("daily_scores").select("date").eq("market", market)
            .order("date", desc=True).limit(1).execute()
        )
        if not latest.data:
            return []
        date = latest.data[0]["date"]
        res = (
            self.client.table("daily_scores").select("*")
            .eq("market", market).eq("date", date).order("sector").execute()
        )
        return res.data

    def get_score_before(self, market: str, sector: str, date: str) -> dict | None:
        res = (
            self.client.table("daily_scores").select("*")
            .eq("market", market).eq("sector", sector).lt("date", date)
            .order("date", desc=True).limit(1).execute()
        )
        return res.data[0] if res.data else None

    def get_sector_history(self, market: str, sector: str, days: int) -> list[dict]:
        res = (
            self.client.table("daily_scores").select("*")
            .eq("market", market).eq("sector", sector)
            .order("date", desc=True).limit(days).execute()
        )
        return list(reversed(res.data))

    # ---- regime_history ----

    def upsert_regime_history(self, rows: list[dict]) -> None:
        if rows:
            self.client.table("regime_history").upsert(
                rows, on_conflict="date,market"
            ).execute()

    def get_latest_regime(self, market: str) -> dict | None:
        res = (
            self.client.table("regime_history").select("*").eq("market", market)
            .order("date", desc=True).limit(1).execute()
        )
        return res.data[0] if res.data else None

    def get_regime_history(self, market: str, days: int) -> list[dict]:
        res = (
            self.client.table("regime_history").select("*").eq("market", market)
            .order("date", desc=True).limit(days).execute()
        )
        return list(reversed(res.data))

    # ---- macro_snapshots ----

    def upsert_macro_snapshot(self, date: str, market: str, payload: dict) -> None:
        self.client.table("macro_snapshots").upsert(
            {"date": date, "market": market, "payload": payload},
            on_conflict="date,market",
        ).execute()

    def get_macro_snapshot(self, market: str, date: str | None = None) -> dict | None:
        q = self.client.table("macro_snapshots").select("payload").eq("market", market)
        if date:
            q = q.eq("date", date)
        else:
            q = q.order("date", desc=True).limit(1)
        res = q.execute()
        return res.data[0]["payload"] if res.data else None

    # ---- notification_events ----

    def insert_notification(
        self, market: str, sector: str | None, event_type: str,
        title: str, body: str, immediate: bool,
    ) -> int:
        res = self.client.table("notification_events").insert(
            {
                "created_at": utcnow_iso(),
                "market": market,
                "sector": sector,
                "event_type": event_type,
                "title": title,
                "body": body,
                "immediate": immediate,
                "delivered": False,
            }
        ).execute()
        return int(res.data[0]["id"])

    def pending_notifications(self) -> list[dict]:
        res = (
            self.client.table("notification_events")
            .select("id, created_at, market, sector, event_type, title, body, immediate")
            .eq("delivered", False).order("id").execute()
        )
        return res.data

    def ack_notifications(self, ids: list[int]) -> int:
        if not ids:
            return 0
        res = (
            self.client.table("notification_events").update({"delivered": True})
            .eq("delivered", False).in_("id", ids).execute()
        )
        return len(res.data)

    # ---- news ----

    def insert_news_items(self, rows: list[dict]) -> None:
        if rows:
            self.client.table("news_items").upsert(
                [
                    {
                        "date": r["date"], "market": r["market"], "sector": r["sector"],
                        "title": r.get("title"), "url": r.get("url"),
                        "source": r.get("source"), "sentiment": r.get("sentiment"),
                    }
                    for r in rows
                ],
                on_conflict="market,sector,url",
                ignore_duplicates=True,
            ).execute()

    def get_news_items(self, market: str, sector: str, limit: int = 20) -> list[dict]:
        res = (
            self.client.table("news_items")
            .select("date, title, url, source, sentiment")
            .eq("market", market).eq("sector", sector)
            .order("date", desc=True).limit(limit).execute()
        )
        return res.data

    def upsert_news_summary(self, date: str, market: str, sector: str, summary: str) -> None:
        self.client.table("news_summaries").upsert(
            {"date": date, "market": market, "sector": sector, "summary": summary},
            on_conflict="date,market,sector",
        ).execute()

    def get_news_summary(self, market: str, sector: str) -> str | None:
        res = (
            self.client.table("news_summaries").select("summary")
            .eq("market", market).eq("sector", sector)
            .order("date", desc=True).limit(1).execute()
        )
        return res.data[0]["summary"] if res.data else None


def get_store(settings=None) -> Store:
    """설정 기반 스토어 팩토리 — Supabase 설정 시 SupabaseStore, 아니면 SQLite."""
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    if settings.supabase_url and settings.supabase_service_key:
        return SupabaseStore(settings.supabase_url, settings.supabase_service_key)
    return SQLiteStore(settings.db_path)
