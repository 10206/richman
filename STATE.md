# 프로젝트 진행 상태 (자동 갱신)

> 이 파일은 Claude가 장시간 자율 작업 중 진행 상황을 추적하기 위해 유지합니다.
> 컨텍스트가 요약되어도 이 파일을 읽으면 어디까지 했는지 알 수 있습니다.

## 페이즈

- [x] P1. 설계 문서 (docs/00~03)
- [x] P2. 시그널 엔진 — 순수 로직 (backend/app/engine) + 단위 테스트 (21개 통과)
- [x] P3. 백테스트 (yfinance/FRED 12년) → docs/04 리포트, 파라미터 확정
- [x] P4. 데이터 클라이언트 + FastAPI + 저장 스키마(SQLite 기본/Supabase 선택) + 배치 잡 — pytest 46개 통과,
  키 없이 US/KR E2E 백필 성공(SQLite), API 스모크 통과
- [x] P5. iOS SwiftUI 앱 (ios/) — 14파일, swiftc -parse 전체 통과, 모의 데이터 모드 내장
- [x] P6. 배포/설치 가이드 (docs/05~06) + 사용자 판단 항목 (docs/07) + README

## 2026-07-02 추가 변경 — 전력 섹터 재정의

사용자 확인: "전력" = 전력기기/인프라 (유틸리티 아님). 반영 완료:
- KR 프록시 117460(임시) → **487240** KODEX AI전력핵심설비 (효성중공업/HD현대일렉트릭/LS ELECTRIC)
- US 프록시 XLU(유틸리티) → **GRID** First Trust Smart Grid Infra (12년 이력으로 재보정)
- 신호 임계값 재확정: enter 50→**60**, exit 30(유지), confirm 3일→**2일** (docs/04 §7)
- bias 매트릭스(G/R/T/F: +1/+1/0/+1)는 재검증 결과 부호 유지 — 변경 없음
- docs/00, 02, 04, 07, backend/AGENT_NOTES.md, sectors.py 갱신 + pytest 46개 재통과 +
  US/KR 로컬 DB 재백필 확인. docs/07 항목 1 해결됨으로 마감.
- GitHub 원격(https://github.com/10206/richman.git)은 세션 환경이 자동 미러링 — 별도 push 불필요.

## 2026-07-02 추가 변경 — 저장소를 Supabase에서 Railway 볼륨+SQLite로 전환

Supabase 무료 티어 프로젝트 개수 한도에 걸림 → 사용자가 SQLite 유지 결정. 반영 완료:
- 코드 변경 없음 (`get_store()`가 이미 SUPABASE_URL 미설정 시 SQLite 폴백하도록 구현돼 있었음,
  `SupabaseStore`는 코드에 그대로 남겨둠 — 원할 때 언제든 SUPABASE_URL만 설정하면 복귀 가능)
- Railway가 볼륨을 서비스당 1개·서비스 간 공유 불가라는 실제 제약을 확인(웹서치로 검증) →
  API 서비스(richman-api)만 볼륨을 갖고, 크론 서비스 2개는 이미 구현된
  `POST /api/v1/jobs/run` 엔드포인트를 curl로 호출만 하는 얇은 트리거로 재설계
  (`curlimages/curl` Docker 이미지 + Railway 네이티브 Cron Schedule)
- 로컬에서 `/api/v1/jobs/run` 증분 실행(~6초) / 백필 실행(~6초) 둘 다 HTTP 요청으로
  안전하게 처리됨을 실측 확인 — Railway CLI(`railway run`) 없이 curl만으로 초기 적재 가능
- docs/00(A9), docs/05(전면 재작성), docs/07(항목 2 해결) 갱신

## 2026-07-02 추가 변경 — Railway 실배포 완료 (CLI로 진행)

프로젝트 `refreshing-expression`(이미 GitHub 연동돼 자동배포 중이던 것 재사용)에 3개 서비스:
- **richman** — API 서비스. 도메인 `https://richman-production.up.railway.app`, 볼륨
  `richman-volume`(`/data`, 5GB), 환경변수 `DB_PATH=/data/richman.db`, `API_KEY` 설정 완료.
  Dockerfile 빌드 성공 (Root Directory가 이미 `backend/`로 잡혀 있어 COPY 경로를 그에 맞춤 —
  저장소 루트 `Dockerfile`/`railway.toml` 참고). US/KR 백필 완료, `/health`·`/dashboard` 응답 확인.
- **richman-cron-kr**, **richman-cron-us** — `curlimages/curl:latest` 기반 경량 트리거 서비스,
  `API_KEY` 변수까지는 CLI로 설정 완료. **Custom Start Command와 Cron Schedule은 Railway CLI가
  지원하지 않아 대시보드에서 수동 설정 필요** (docs/05 §3 참고, 정확한 값 명시돼 있음) — 이
  두 필드 4칸이 유일하게 남은 수동 작업.
- API_KEY 실제 값은 보안상 이 세션의 도구 출력에 남기지 않음 — 사용자가 직접
  `railway variable list --kv -s richman` (본인 터미널) 또는 Railway 대시보드에서 확인.

## 통합 검증 기록

- 백엔드↔iOS 계약 교차 검증: local_trend 타입 불일치(숫자 vs 문자열) 발견 →
  API 계층에서 "bull"/"neutral"/"bear" 문자열로 변환하도록 수정 완료 (routes.py)
- 남은 실검증 항목 (환경 제약상 이 머신에서 불가):
  1. Xcode 첫 빌드 (iOS 전용 API 타입 체크) — 사용자 머신에서 xcodegen generate 후 ⌘R
  2. KIS/ECOS 실키 투입 후 첫 파이프라인 실행, Railway 실배포(3서비스+볼륨) 첫 검증
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
    vix, hy_spread, real_rate?, dollar_index?, news_score?, news_z?},
    basket: {market, proxy:{ticker,name}, asset_type(equity_etf|commodity|bond), constituents:[{ticker,name}], note?},
    news_summary: str|null, news_items: [{date, title, url, source, sentiment}]}`
- `GET /api/v1/regime/history?market=US&days=365` → `{items: [{date, regime, r_score, l_score, local_trend}]}`
- `local_trend`는 문자열 "bull"|"neutral"|"bear" (엔진 내부 수치 1.0/0.5/0.0을 API 계층에서 변환)
- `GET /api/v1/notifications/pending` → `{items: [{id, created_at, market, sector, event_type, title, body, immediate}]}`
- `POST /api/v1/notifications/ack` body `{ids: [int]}` → `{acked: n}`
- `GET /api/v1/calendar?month=YYYY-MM` → `{month, events: [{date, market(US|KR), category(earnings|macro), title, importance(1~3), confirmed(bool), sector?}]}`
  (실적=AV 확정일 confirmed=true, 거시=정례주기 예상 confirmed=false. month 없으면 현재 월)
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
