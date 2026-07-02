"""FastAPI 스모크/계약 테스트 — TestClient + 임시 SQLite.

STATE.md의 API 계약(응답 스키마)을 고정하는 회귀 테스트.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.store import SQLiteStore
from app.main import create_app


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(str(tmp_path / "api.db"))
    # 이틀치 데이터 시드 (직전 거래일 비교 검증용)
    s.upsert_daily_scores([
        {"date": "2026-06-30", "market": "US", "sector": "semiconductor",
         "score": 40.0, "trend": 0.4, "volume": 0.5, "macro": 0.4,
         "w_trend": 0.35, "w_volume": 0.2, "w_macro": 0.45,
         "signal": "cash", "stance": "CASH", "regime": "T"},
        {"date": "2026-07-01", "market": "US", "sector": "semiconductor",
         "score": 61.5, "trend": 0.7, "volume": 0.6, "macro": 0.55,
         "w_trend": 0.5, "w_volume": 0.25, "w_macro": 0.25,
         "signal": "hold", "stance": "LONG", "regime": "G"},
        {"date": "2026-07-01", "market": "US", "sector": "gold",
         "score": 52.0, "trend": 0.5, "volume": 0.5, "macro": 0.55,
         "w_trend": 0.3, "w_volume": 0.1, "w_macro": 0.6,
         "signal": "keep", "stance": "LONG", "regime": "G"},
    ])
    s.upsert_regime_history([
        {"date": "2026-07-01", "market": "US", "regime": "G",
         "r_score": 0.45, "l_score": -0.2, "local_trend": 1.0},
    ])
    s.upsert_macro_snapshot("2026-07-01", "US", {
        "y_short": 3.8, "y_long": 4.2, "y_long_chg_63d": -0.15,
        "vix": 14.5, "hy_spread": 3.1, "real_rate": 1.9, "dollar_index": 121.3,
        "degraded": False,
        "news": {"semiconductor": {"news_score": 0.62, "news_z": 1.3}},
    })
    s.insert_news_items([
        {"date": "2026-07-01", "market": "US", "sector": "semiconductor",
         "title": "칩 수요 급증", "url": "http://n/1", "source": "src", "sentiment": 0.5},
    ])
    s.upsert_news_summary("2026-07-01", "US", "semiconductor", "반도체 수요가 강합니다. 공급은 타이트합니다.")
    s.insert_notification("US", "semiconductor", "signal_change",
                          "[US] 반도체 신호 전환", "현금보유 → 보유", immediate=False)
    yield s
    s.close()


@pytest.fixture
def client(store):
    app = create_app(settings=Settings(api_key=None, db_path=":memory:"), store=store)
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


class TestDashboard:
    def test_contract_shape(self, client):
        r = client.get("/api/v1/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["as_of"] == "2026-07-01"
        assert "generated_at" in body
        us = body["markets"]["US"]
        assert us["regime"] == "G"
        assert us["regime_label"] == "이상적 성장 국면"
        assert {"r_score", "l_score", "local_trend"} <= set(us)

        sectors = {s["sector"]: s for s in body["sectors"]}
        semi = sectors["semiconductor"]
        for key in ("market", "sector", "label", "score", "trend", "volume", "macro",
                    "w_trend", "w_volume", "w_macro", "signal", "stance",
                    "prev_signal", "signal_changed", "score_delta_1d"):
            assert key in semi
        assert semi["label"] == "반도체"
        assert semi["prev_signal"] == "cash"
        assert semi["signal_changed"] is True        # CASH → LONG
        assert semi["score_delta_1d"] == pytest.approx(21.5)
        gold = sectors["gold"]
        assert gold["prev_signal"] is None            # 직전일 없음
        assert gold["signal_changed"] is False


class TestSectorEndpoints:
    def test_history(self, client):
        r = client.get("/api/v1/sectors/US/semiconductor/history?days=180")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        assert items[0]["date"] == "2026-06-30"       # 오름차순
        assert {"date", "score", "trend", "volume", "macro",
                "signal", "stance", "regime"} <= set(items[0])

    def test_detail(self, client):
        r = client.get("/api/v1/sectors/US/semiconductor/detail")
        assert r.status_code == 200
        body = r.json()
        assert body["sector"]["signal"] == "hold"
        assert body["regime_bias"] == 2               # 반도체 × G국면 = +2
        raw = body["macro_raw"]
        assert raw["vix"] == 14.5
        assert raw["news_score"] == 0.62
        assert raw["news_z"] == 1.3
        assert "수요" in body["news_summary"]
        assert body["news_items"][0]["url"] == "http://n/1"

    def test_unknown_market_and_sector_404(self, client):
        assert client.get("/api/v1/sectors/JP/gold/history").status_code == 404
        assert client.get("/api/v1/sectors/US/crypto/detail").status_code == 404


class TestRegimeAndNotifications:
    def test_regime_history(self, client):
        r = client.get("/api/v1/regime/history?market=US&days=365")
        assert r.status_code == 200
        items = r.json()["items"]
        assert items[-1]["regime"] == "G"
        assert {"date", "regime", "r_score", "l_score", "local_trend"} <= set(items[0])

    def test_notifications_pending_then_ack(self, client):
        r = client.get("/api/v1/notifications/pending")
        items = r.json()["items"]
        assert len(items) == 1
        assert {"id", "created_at", "market", "sector",
                "event_type", "title", "body", "immediate"} <= set(items[0])

        r2 = client.post("/api/v1/notifications/ack", json={"ids": [items[0]["id"]]})
        assert r2.json() == {"acked": 1}
        assert client.get("/api/v1/notifications/pending").json()["items"] == []

    def test_ack_validation(self, client):
        assert client.post("/api/v1/notifications/ack", json={"ids": "1"}).status_code == 422


class TestAuth:
    def test_api_key_enforced_when_configured(self, store):
        app = create_app(settings=Settings(api_key="secret", db_path=":memory:"), store=store)
        c = TestClient(app)
        assert c.get("/health").status_code == 200                       # health는 공개
        assert c.get("/api/v1/dashboard").status_code == 401             # 키 없음
        assert c.get("/api/v1/dashboard", headers={"X-API-Key": "nope"}).status_code == 401
        assert c.get("/api/v1/dashboard", headers={"X-API-Key": "secret"}).status_code == 200

    def test_jobs_run_requires_configured_key(self, client):
        # API_KEY 미설정 → 원격 잡 실행 자체가 비활성화 (403)
        r = client.post("/api/v1/jobs/run?market=US")
        assert r.status_code == 403


class TestCalendar:
    def test_macro_events_deterministic(self):
        from app.data import market_calendar as mc
        ev = mc.macro_events(2026, 7)
        assert len(ev) > 0
        # 모든 거시 이벤트는 예상(confirmed=False), 해당 월
        assert all(e["confirmed"] is False for e in ev)
        assert all(e["date"].startswith("2026-07") for e in ev)
        # 미국 고용보고서 = 첫째 주 금요일 (2026-07-03)
        nfp = [e for e in ev if "고용보고서" in e["title"]]
        assert nfp and nfp[0]["date"] == "2026-07-03"
        # 미국/한국 둘 다 포함
        assert {"US", "KR"} <= {e["market"] for e in ev}

    def test_calendar_endpoint(self, client):
        r = client.get("/api/v1/calendar?month=2026-07")
        assert r.status_code == 200
        body = r.json()
        assert body["month"] == "2026-07"
        assert isinstance(body["events"], list) and len(body["events"]) > 0
        e = body["events"][0]
        assert {"date", "market", "category", "title", "importance", "confirmed"} <= set(e)
        # 날짜 오름차순 정렬
        dates = [x["date"] for x in body["events"]]
        assert dates == sorted(dates)

    def test_calendar_bad_month(self, client):
        assert client.get("/api/v1/calendar?month=2026-13").status_code == 422
