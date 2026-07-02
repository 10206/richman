# 프로젝트 진행 상태 (자동 갱신)

> 이 파일은 Claude가 장시간 자율 작업 중 진행 상황을 추적하기 위해 유지합니다.
> 컨텍스트가 요약되어도 이 파일을 읽으면 어디까지 했는지 알 수 있습니다.

## 페이즈

- [x] P1. 설계 문서 (docs/00~03)
- [x] P2. 시그널 엔진 — 순수 로직 (backend/app/engine) + 단위 테스트 (21개 통과)
- [x] P3. 백테스트 (yfinance/FRED 12년) → docs/04 리포트, 파라미터 확정
- [x] P4. 데이터 클라이언트 + FastAPI + Supabase 스키마 + 배치 잡 — pytest 46개 통과,
  키 없이 US/KR E2E 백필 성공(SQLite), API 스모크 통과
- [x] P5. iOS SwiftUI 앱 (ios/) — 14파일, swiftc -parse 전체 통과, 모의 데이터 모드 내장
- [x] P6. 배포/설치 가이드 (docs/05~06) + 사용자 판단 항목 (docs/07) + README

## 통합 검증 기록

- 백엔드↔iOS 계약 교차 검증: local_trend 타입 불일치(숫자 vs 문자열) 발견 →
  API 계층에서 "bull"/"neutral"/"bear" 문자열로 변환하도록 수정 완료 (routes.py)
- 남은 실검증 항목 (환경 제약상 이 머신에서 불가):
  1. Xcode 첫 빌드 (iOS 전용 API 타입 체크) — 사용자 머신에서 xcodegen generate 후 ⌘R
  2. KIS/ECOS/Supabase 실키 투입 후 첫 파이프라인 실행
  3. 한국 데이터 백테스트 재검증 (docs/04 §6)

## API 계약 (P4 백엔드 ↔ P5 iOS 공유, 변경 금지)

- 인증: `X-API-Key` 헤더 (env `API_KEY` 미설정 시 인증 생략 — 로컬 개발)
- `GET /health` → `{"status":"ok"}`
- `GET /api/v1/dashboard` →
  `{as_of, generated_at, markets: {US: {regime, regime_label, r_score, l_score, local_trend}, KR: {...}},
    sectors: [{market, sector, label, score, trend, volume, macro, w_trend, w_volume, w_macro,
               signal(hold|cash|keep), stance(LONG|CASH), prev_signal, signal_changed(bool), score_delta_1d}]}`
- `GET /api/v1/sectors/{market}/{sector}/history?days=180` →
  `{items: [{date, score, trend, volume, macro, signal, stance, regime}]}`
- `GET /api/v1/sectors/{market}/{sector}/detail` →
  `{sector: <dashboard 항목과 동일>, regime_bias: int(-2~2), macro_raw: {y_short, y_long, y_long_chg_63d,
    vix, hy_spread, real_rate?, dollar_index?, news_score?, news_z?}, news_summary: str|null,
    news_items: [{date, title, url, source, sentiment}]}`
- `GET /api/v1/regime/history?market=US&days=365` → `{items: [{date, regime, r_score, l_score, local_trend}]}`
- `local_trend`는 문자열 "bull"|"neutral"|"bear" (엔진 내부 수치 1.0/0.5/0.0을 API 계층에서 변환)
- `GET /api/v1/notifications/pending` → `{items: [{id, created_at, market, sector, event_type, title, body, immediate}]}`
- `POST /api/v1/notifications/ack` body `{ids: [int]}` → `{acked: n}`
- `POST /api/v1/jobs/run?market=KR|US` (키 필수) → 파이프라인 실행 결과 요약
- 날짜는 "YYYY-MM-DD", 시각은 ISO8601 UTC. sector 값: semiconductor|robotics|power|healthcare|gold|bonds

## 환경 제약 (확인됨)

- Python 3.13 사용 가능, 네트워크 OK (FRED/ECOS/stooq 접근 확인)
- **Xcode 미설치** (CommandLineTools만 있음) → 시뮬레이터 빌드 검증 불가.
  Swift 문법 검증(`swiftc -parse`) + XcodeGen 프로젝트 + 설치 가이드로 대체.
- 기존 KIS API / KR-FinBert-SC 코드는 이 머신에서 참조 불가 → 공식 스펙 기반 신규 작성.
- ECOS/FRED/KIS API 키 없음 → 백테스트는 키 불필요한 소스(fredgraph CSV, stooq) 사용,
  프로덕션 코드는 환경변수로 키 주입.

## 현재 작업

P1 설계 문서 작성 중.
