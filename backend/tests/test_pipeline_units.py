"""daily_pipeline 순수 로직 단위 테스트 — 네트워크 없이 검증 가능한 부분만."""

import math

import pytest

from app.db.store import SQLiteStore
from app.engine.sectors import Market, Sector
from app.jobs.daily_pipeline import _f, detect_and_notify


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(str(tmp_path / "p.db"))
    yield s
    s.close()


def _row(stance="LONG", signal="hold", regime="G", **kw):
    row = {
        "date": "2026-07-01", "market": "US", "sector": "semiconductor",
        "score": 60.0, "trend": 0.7, "volume": 0.5, "macro": 0.6,
        "w_trend": 0.5, "w_volume": 0.25, "w_macro": 0.25,
        "signal": signal, "stance": stance, "regime": regime,
    }
    row.update(kw)
    return row


class TestDetectAndNotify:
    def test_long_to_cash_is_immediate(self, store):
        prev = _row(stance="LONG", date="2026-06-30", trend=0.7)
        new = _row(stance="CASH", signal="cash", regime="T", trend=0.3, score=30.0)
        nid = detect_and_notify(store, Market.US, Sector.SEMICONDUCTOR, new, prev, regime_changed=True)
        assert nid is not None
        ev = store.pending_notifications()[0]
        assert ev["immediate"] is True                 # 현금보유 전환은 즉시
        assert ev["event_type"] == "signal_change"
        assert "보유 → 현금보유" in ev["title"]
        assert "긴축 스트레스 국면 진입" in ev["body"]   # build_reason 경유
        assert "추세" in ev["body"]                     # 최대 변화 컴포넌트

    def test_cash_to_long_is_digest(self, store):
        prev = _row(stance="CASH", signal="cash", date="2026-06-30")
        new = _row(stance="LONG", signal="hold", score=65.0)
        detect_and_notify(store, Market.US, Sector.SEMICONDUCTOR, new, prev, regime_changed=False)
        ev = store.pending_notifications()[0]
        assert ev["immediate"] is False                # 그 외는 다이제스트

    def test_no_transition_no_event(self, store):
        prev = _row(date="2026-06-30")
        new = _row()
        assert detect_and_notify(store, Market.US, Sector.SEMICONDUCTOR, new, prev, False) is None
        assert detect_and_notify(store, Market.US, Sector.SEMICONDUCTOR, new, None, False) is None
        assert store.pending_notifications() == []


class TestCleanFloat:
    def test_nan_and_none(self):
        assert _f(float("nan")) is None
        assert _f(None) is None
        assert _f("abc") is None

    def test_rounding(self):
        assert _f(0.123456) == 0.1235
        assert not math.isnan(_f(1.0))
