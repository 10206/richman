"""웹 푸시(PWA) 발송 — VAPID + pywebpush.

설계 근거:
  - VAPID 키(settings.vapid_*)가 없으면 조용히 비활성 (앱/파이프라인은 정상 동작).
  - pywebpush/cryptography는 지연 import — 키 없는 환경에선 패키지 없어도 됨.
  - 발송 정책은 백엔드가 만든 notification_events를 그대로 사용:
      · immediate=True (현금보유 전환) → 개별 즉시 푸시
      · immediate=False (보유 전환·국면 변경) → 1건이면 개별, 여러 건이면 다이제스트 1건
  - 만료(404/410) 구독은 자동 삭제. 발송 성공 여부와 무관하게 pushed=1 표시
    (전송 재시도로 중복 알림이 쌓이는 것을 방지 — 개인용 1인 앱 기준).
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

logger = logging.getLogger("richman.push")

_vapid_cache: object | None = None
_vapid_key_fingerprint: str | None = None


def push_enabled(settings) -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def _load_vapid(settings):
    """settings의 개인키(PEM 또는 base64url raw)로 Vapid 인스턴스 생성 (캐시)."""
    global _vapid_cache, _vapid_key_fingerprint
    key = settings.vapid_private_key or ""
    if _vapid_cache is not None and _vapid_key_fingerprint == key:
        return _vapid_cache

    from py_vapid import Vapid01

    if "BEGIN" in key:  # PEM
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        priv = load_pem_private_key(key.encode(), password=None)
        v = Vapid01(private_key=priv)
    else:  # base64url raw (32바이트)
        v = Vapid01.from_raw(key.encode())

    _vapid_cache = v
    _vapid_key_fingerprint = key
    return v


def _send_one(subscription: dict, payload: str, settings) -> tuple[bool, bool]:
    """구독 1건에 발송. 반환 (성공, 만료됨). 만료(410/404)면 구독 삭제 대상."""
    from pywebpush import WebPushException, webpush

    sub_info = {
        "endpoint": subscription["endpoint"],
        "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
    }
    try:
        webpush(
            subscription_info=sub_info,
            data=payload,
            vapid_private_key=_load_vapid(settings),
            vapid_claims={"sub": settings.vapid_subject},
            ttl=60 * 60 * 12,  # 12시간 (수신 못 하면 폐기)
        )
        return True, False
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            return False, True  # 만료 — 삭제
        logger.warning("웹 푸시 실패 (%s): %s", status, e)
        return False, False
    except Exception as e:  # noqa: BLE001 — 발송 실패가 파이프라인을 죽이면 안 됨
        logger.warning("웹 푸시 예외: %s", e)
        return False, False


def _payload(title: str, body: str, tag: str, market: str | None, sector: str | None) -> str:
    return json.dumps(
        {
            "title": title,
            "body": body,
            "tag": tag,
            "url": "/",
            "market": market,
            "sector": sector,
        },
        ensure_ascii=False,
    )


def _messages_from_events(events: list[dict]) -> list[tuple[str, str, str, str | None, str | None]]:
    """이벤트 목록 → (title, body, tag, market, sector) 푸시 메시지 목록."""
    immediate = [e for e in events if e.get("immediate")]
    digest = [e for e in events if not e.get("immediate")]
    msgs: list[tuple[str, str, str, str | None, str | None]] = []

    for e in immediate:
        msgs.append((e["title"], e["body"], f"richsignal-{e['id']}", e.get("market"), e.get("sector")))

    if len(digest) == 1:
        e = digest[0]
        msgs.append((e["title"], e["body"], f"richsignal-{e['id']}", e.get("market"), e.get("sector")))
    elif len(digest) > 1:
        lines = [f"· {e['title']}" for e in digest]
        msgs.append(
            (
                f"신호 변경 {len(digest)}건",
                "\n".join(lines),
                "richsignal-digest",
                None,
                None,
            )
        )
    return msgs


def dispatch_new_notifications(store, settings) -> int:
    """아직 푸시 안 한 알림 이벤트를 웹 푸시로 발송. 발송한 이벤트 수 반환.

    파이프라인 말미에서 호출 (예외는 삼켜 파이프라인에 영향 없음).
    """
    if not push_enabled(settings):
        return 0
    try:
        events = store.unpushed_notifications()
    except Exception as e:  # noqa: BLE001
        logger.warning("unpushed 조회 실패: %s", e)
        return 0
    if not events:
        return 0

    subs = store.list_push_subscriptions()
    if subs:
        messages = _messages_from_events(events)
        gone: list[str] = []
        for title, body, tag, market, sector in messages:
            payload = _payload(title, body, tag, market, sector)
            for sub in subs:
                ok, expired = _send_one(sub, payload, settings)
                if expired:
                    gone.append(sub["endpoint"])
        for endpoint in set(gone):
            try:
                store.remove_push_subscription(endpoint)
            except Exception:  # noqa: BLE001
                pass

    # 구독이 없어도 pushed 표시 (없는 동안 쌓인 알림이 나중에 폭주하지 않도록)
    store.mark_pushed([e["id"] for e in events])
    return len(events)


def send_test_push(store, settings) -> dict:
    """설정 확인용 테스트 푸시 — 모든 구독에 즉시 1건 발송."""
    if not push_enabled(settings):
        return {"sent": 0, "reason": "VAPID 키 미설정"}
    subs = store.list_push_subscriptions()
    payload = _payload(
        "리치시그널 테스트 알림", "웹 푸시가 정상 동작합니다.", "richsignal-test", None, None
    )
    sent, gone = 0, []
    for sub in subs:
        ok, expired = _send_one(sub, payload, settings)
        sent += int(ok)
        if expired:
            gone.append(sub["endpoint"])
    for endpoint in set(gone):
        try:
            store.remove_push_subscription(endpoint)
        except Exception:  # noqa: BLE001
            pass
    return {"sent": sent, "subscriptions": len(subs)}


def endpoint_origin(endpoint: str) -> str:
    p = urlparse(endpoint)
    return f"{p.scheme}://{p.netloc}"
