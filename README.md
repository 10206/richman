# richman — 개인용 매매신호 앱

한국(KRX)·미국(NYSE/NASDAQ)의 6개 섹터(반도체·로봇·전력·헬스케어·금·국채)에 대해
**보유 / 현금보유 / 유지** 신호를 매일 계산해 웹 앱(PWA)으로 보여주는 개인용 시스템.
자동매매 아님 — 신호만 제공, 실행은 수동.

## 구조

```
docs/       설계 문서 (국면 프레임워크, 스코어링, 백테스트 리포트, 배포/설치 가이드)
backend/    FastAPI + 시그널 엔진 (순수 파이썬 수식, LLM 없음) + 배치 파이프라인
            + PWA 웹 앱 (app/web/, 같은 서버에서 정적 서빙 + 웹 푸시)
```

> 초기엔 SwiftUI 네이티브 앱(구 `ios/`)이었으나, 무료 서명 7일 만료를 없애기 위해
> PWA로 전환(2026-07). 네이티브 소스는 git 이력에 남아 있음.

## 핵심 설계

- **거시 국면**: 위험선호(R축) × 금리방향(L축) → 4국면 G/R/T/F. 시장별(KR/US) 독립 판정 (docs/01)
- **섹터 점수**: 추세(T)+거래량(V)+거시(M) 가중합 0~100, 국면별 가중치 조정 (docs/02)
- **신호**: 임계값 + 히스테리시스 + 확인일 + 쿨다운 — 12년 백테스트로 파라미터 확정 (docs/04)
- **알림**: 신호가 바뀔 때만. 현금보유 전환은 즉시, 나머지는 다이제스트. 웹 푸시(VAPID) (docs/03)

## 빠른 시작

```bash
# 백엔드 (키 없이도 동작 — yfinance/FRED 폴백). PWA 웹 앱도 이 서버가 함께 서빙.
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.jobs.daily_pipeline --market US --backfill
.venv/bin/uvicorn app.main:app --reload
# → 브라우저로 http://localhost:8000 접속 (배포본: https://richman-production.up.railway.app)
```

- 배포(Railway, 볼륨+SQLite): docs/05-DEPLOYMENT.md
- 아이폰 홈 화면 설치(PWA): docs/06-PWA-INSTALL.md
- 백테스트 재현: `cd backend && .venv/bin/python backtest/run_backtest.py`
- **사용자 확인 필요 항목: docs/07-DECISIONS-FOR-USER.md**

## 면책

개인 학습/참고용 신호이며 투자 손익의 책임은 사용자에게 있음. 과거 성과(백테스트)는
미래 수익을 보장하지 않음.
