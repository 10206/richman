"""환경설정 — pydantic-settings 기반.

설계 근거:
  - 모든 외부 키는 optional. 키가 없으면 각 모듈이 폴백(yfinance/FRED CSV)으로
    동작하거나 해당 기능을 조용히 스킵한다 (가정 A9: 로컬은 SQLite 폴백).
  - .env 로딩 지원 (로컬 개발), 프로덕션(Railway)은 환경변수 주입.
  - 키를 코드에 하드코딩하지 않는다 (CLAUDE.md 보안 원칙).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수 스키마. 전부 optional — 없으면 폴백 동작."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 저장 계층 — SUPABASE_URL 설정 시 SupabaseStore, 아니면 SQLiteStore
    supabase_url: str | None = None
    supabase_service_key: str | None = None
    db_path: str = "./richman.db"

    # API 인증 (설정 시에만 X-API-Key 강제)
    api_key: str | None = None

    # 거시 데이터
    fred_api_key: str | None = None
    ecos_api_key: str | None = None

    # 시세 (KIS Developers)
    kis_app_key: str | None = None
    kis_app_secret: str | None = None
    kis_account: str | None = None

    # 뉴스 감성
    alphavantage_api_key: str | None = None
    news_kr_enabled: bool = False  # KR-FinBert-SC 통합 전까지 기본 꺼짐 (스텁)

    # 뉴스 요약 (Claude Haiku, 표시용 — 신호 계산에는 사용 금지)
    anthropic_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """설정 싱글턴. 테스트에서는 get_settings.cache_clear() 후 환경변수 주입."""
    return Settings()
