"""SQLiteStore 단위 테스트 — upsert 멱등성, 조회, 알림 라이프사이클."""

import pytest

from app.db.store import SQLiteStore


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(str(tmp_path / "test.db"))
    yield s
    s.close()


def _score_row(date="2026-07-01", market="US", sector="semiconductor", **kw):
    row = {
        "date": date, "market": market, "sector": sector,
        "score": 62.5, "trend": 0.7, "volume": 0.55, "macro": 0.6,
        "w_trend": 0.5, "w_volume": 0.25, "w_macro": 0.25,
        "signal": "hold", "stance": "LONG", "regime": "G",
    }
    row.update(kw)
    return row


class TestDailyScores:
    def test_upsert_idempotent(self, store):
        store.upsert_daily_scores([_score_row()])
        store.upsert_daily_scores([_score_row(score=70.0)])  # 같은 키 → 갱신
        rows = store.get_latest_scores("US")
        assert len(rows) == 1
        assert rows[0]["score"] == 70.0

    def test_latest_scores_returns_max_date_only(self, store):
        store.upsert_daily_scores([
            _score_row(date="2026-06-30", score=50.0),
            _score_row(date="2026-07-01", score=60.0),
            _score_row(date="2026-07-01", sector="gold", score=55.0),
        ])
        rows = store.get_latest_scores("US")
        assert {r["date"] for r in rows} == {"2026-07-01"}
        assert len(rows) == 2

    def test_score_before(self, store):
        store.upsert_daily_scores([
            _score_row(date="2026-06-27", score=45.0, stance="CASH", signal="cash"),
            _score_row(date="2026-06-30", score=58.0),
        ])
        prev = store.get_score_before("US", "semiconductor", "2026-06-30")
        assert prev["date"] == "2026-06-27"
        assert prev["stance"] == "CASH"
        assert store.get_score_before("US", "semiconductor", "2026-06-27") is None

    def test_history_order_and_limit(self, store):
        store.upsert_daily_scores([
            _score_row(date=f"2026-06-{d:02d}") for d in range(1, 11)
        ])
        rows = store.get_sector_history("US", "semiconductor", days=5)
        assert len(rows) == 5
        assert rows[0]["date"] < rows[-1]["date"]  # 오름차순
        assert rows[-1]["date"] == "2026-06-10"

    def test_market_isolation(self, store):
        store.upsert_daily_scores([
            _score_row(market="US"), _score_row(market="KR", score=40.0),
        ])
        assert len(store.get_latest_scores("US")) == 1
        assert store.get_latest_scores("KR")[0]["score"] == 40.0


class TestRegimeHistory:
    def test_upsert_and_latest(self, store):
        store.upsert_regime_history([
            {"date": "2026-06-30", "market": "US", "regime": "T",
             "r_score": -0.4, "l_score": 0.3, "local_trend": 0.0},
            {"date": "2026-07-01", "market": "US", "regime": "G",
             "r_score": 0.5, "l_score": -0.2, "local_trend": 1.0},
        ])
        latest = store.get_latest_regime("US")
        assert latest["regime"] == "G"
        assert latest["date"] == "2026-07-01"
        # 멱등 갱신
        store.upsert_regime_history([
            {"date": "2026-07-01", "market": "US", "regime": "R",
             "r_score": 0.6, "l_score": 0.4, "local_trend": 1.0},
        ])
        assert store.get_latest_regime("US")["regime"] == "R"
        hist = store.get_regime_history("US", days=10)
        assert len(hist) == 2
        assert hist[0]["date"] == "2026-06-30"


class TestMacroSnapshots:
    def test_upsert_and_get(self, store):
        store.upsert_macro_snapshot("2026-07-01", "US", {"vix": 15.2, "degraded": False})
        store.upsert_macro_snapshot("2026-07-01", "US", {"vix": 16.0, "degraded": False})
        snap = store.get_macro_snapshot("US")
        assert snap["vix"] == 16.0
        assert store.get_macro_snapshot("US", "2026-07-01")["vix"] == 16.0
        assert store.get_macro_snapshot("KR") is None


class TestNotifications:
    def test_lifecycle(self, store):
        nid = store.insert_notification("US", "semiconductor", "signal_change",
                                        "제목", "본문", immediate=True)
        store.insert_notification("US", None, "regime_change", "국면", "본문2", immediate=False)
        pending = store.pending_notifications()
        assert len(pending) == 2
        assert pending[0]["immediate"] is True
        assert pending[1]["sector"] is None

        acked = store.ack_notifications([nid])
        assert acked == 1
        assert len(store.pending_notifications()) == 1
        # 이미 ack된 id 재-ack → 0
        assert store.ack_notifications([nid]) == 0
        assert store.ack_notifications([]) == 0


class TestPush:
    def test_unpushed_and_mark(self, store):
        a = store.insert_notification("US", "gold", "signal_change", "제목A", "본문", immediate=True)
        b = store.insert_notification("KR", None, "regime_change", "제목B", "본문", immediate=False)
        unp = store.unpushed_notifications()
        assert {r["id"] for r in unp} == {a, b}
        assert unp[0]["immediate"] is True
        assert store.mark_pushed([a]) == 1
        assert {r["id"] for r in store.unpushed_notifications()} == {b}
        assert store.mark_pushed([a]) == 0  # 이미 pushed
        # pushed는 delivered(pull ack)와 독립
        assert len(store.pending_notifications()) == 2

    def test_subscription_lifecycle(self, store):
        store.add_push_subscription("https://ep/1", "p1", "a1")
        store.add_push_subscription("https://ep/2", "p2", "a2")
        subs = store.list_push_subscriptions()
        assert {s["endpoint"] for s in subs} == {"https://ep/1", "https://ep/2"}
        # 같은 endpoint 재등록 → 키 갱신, 중복 없음
        store.add_push_subscription("https://ep/1", "p1new", "a1new")
        subs = store.list_push_subscriptions()
        assert len(subs) == 2
        assert next(s for s in subs if s["endpoint"] == "https://ep/1")["p256dh"] == "p1new"
        assert store.remove_push_subscription("https://ep/1") == 1
        assert store.remove_push_subscription("https://ep/1") == 0
        assert len(store.list_push_subscriptions()) == 1


class TestPushMessages:
    def test_immediate_individual_digest_grouped(self):
        from app.push import _messages_from_events

        events = [
            {"id": 1, "title": "즉시A", "body": "b", "immediate": True, "market": "US", "sector": "gold"},
            {"id": 2, "title": "다이제스트B", "body": "b", "immediate": False, "market": "KR", "sector": "bonds"},
            {"id": 3, "title": "다이제스트C", "body": "b", "immediate": False, "market": "US", "sector": None},
        ]
        msgs = _messages_from_events(events)
        # 즉시 1건 개별 + 다이제스트 2건 → 묶음 1건 = 총 2 메시지
        assert len(msgs) == 2
        titles = [m[0] for m in msgs]
        assert "즉시A" in titles
        assert any("2건" in t for t in titles)

    def test_single_digest_stays_individual(self):
        from app.push import _messages_from_events

        events = [{"id": 5, "title": "단일", "body": "b", "immediate": False, "market": "US", "sector": "gold"}]
        msgs = _messages_from_events(events)
        assert len(msgs) == 1
        assert msgs[0][0] == "단일"


class TestNews:
    def test_items_dedupe_and_query(self, store):
        item = {"date": "2026-07-01", "market": "US", "sector": "gold",
                "title": "금 급등", "url": "http://x/1", "source": "src", "sentiment": 0.4}
        store.insert_news_items([item])
        store.insert_news_items([item])  # 같은 url → 무시
        items = store.get_news_items("US", "gold")
        assert len(items) == 1
        assert items[0]["title"] == "금 급등"

    def test_summary_upsert_and_latest(self, store):
        store.upsert_news_summary("2026-06-30", "US", "gold", "옛 요약")
        store.upsert_news_summary("2026-07-01", "US", "gold", "새 요약")
        store.upsert_news_summary("2026-07-01", "US", "gold", "덮어쓴 요약")
        assert store.get_news_summary("US", "gold") == "덮어쓴 요약"
        assert store.get_news_summary("KR", "gold") is None
