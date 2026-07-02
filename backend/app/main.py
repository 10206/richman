"""FastAPI 앱 엔트리포인트 — `uvicorn app.main:app`.

설계 근거:
  - X-API-Key 인증은 미들웨어로 처리하되 API_KEY 미설정 시 생략 (STATE.md —
    로컬 개발 편의). /health는 항상 공개 (Railway 헬스체크용).
  - CORS 전면 허용: 개인용 1인 앱 + 키 인증이 별도로 있으므로 브라우저 제약 불필요.
  - 스토어는 앱 생성 시 1회 주입 (app.state.store) — 테스트에서 교체 가능.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import Settings, get_settings
from app.db.store import Store, get_store


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="richman — 매매신호 백엔드", version="0.4.0")
    app.state.settings = settings
    app.state.store = store or get_store(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def api_key_guard(request: Request, call_next):
        """API_KEY 설정 시에만 /api/* 경로에 X-API-Key 강제."""
        expected = app.state.settings.api_key
        if expected and request.url.path.startswith("/api/") and request.method != "OPTIONS":
            if request.headers.get("X-API-Key") != expected:
                return JSONResponse(status_code=401, content={"detail": "invalid or missing X-API-Key"})
        return await call_next(request)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()
