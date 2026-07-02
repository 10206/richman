# P4 구현 노트 — 에이전트가 세운 가정/결정 기록

> P4(데이터 클라이언트 + 저장 계층 + 배치 + FastAPI) 구현 중 막힌 지점과 결정.
> engine/, backtest/는 요구사항대로 **무수정** (수정이 필요한 사항도 발견되지 않음).

## A-P4-1. KIS 클라이언트는 실검증 불가 — 공식 스펙 기반 작성

- KIS 앱키가 이 환경에 없어 `app/data/kis.py`는 공식 OpenAPI 문서 스펙으로 작성.
  - 국내 일봉(FHKST03010100): 1회 최대 ~100건 가정 → 최고(最古) 반환일 이전으로
    조회 구간을 옮기는 페이징 구현.
  - 해외 일봉(HHDFS76240000): BYMD(기준일) 과거 방향 페이징.
  - 토큰(POST /oauth2/tokenP)은 `.kis_token.json`에 24시간 캐시 (발급 횟수 제한 대응).
    **이 파일은 커밋 금지** (토큰 포함).
- 실 키 투입 후 첫 실행에서 컬럼명(stck_clpr/acml_vol, clos/tvol)과 페이징을 검증할 것.
  KIS 실패 시 `prices.py`가 경고 로그 후 yfinance로 자동 폴백하므로 파이프라인은 안 죽음.

## A-P4-2. Supabase는 실검증 불가 — 인터페이스 계약만 고정 (2026-07-02: 기본 경로 아님)

- 실 Supabase 프로젝트가 없어 `SupabaseStore`는 supabase-py upsert(on_conflict) 스펙
  기반으로 작성. `migrations/001_init.sql`을 Supabase SQL Editor에서 실행하면 스키마 준비
  완료. RLS는 켜되 정책 없음 = service key(백엔드)만 접근 가능.
- 로컬/CI 검증은 동일 인터페이스의 SQLiteStore로 수행(tests/test_store.py).
- **2026-07-02**: Supabase 무료 티어 한도 이슈로 프로덕션 기본 경로를 Railway 볼륨+SQLite로
  변경(docs/00 A9, docs/05). `SupabaseStore`는 코드에 그대로 남아 있고 `SUPABASE_URL` 설정
  시 자동 활성화되는 선택적 백엔드로 유지 — 위 검증 상태(미검증)는 그대로 적용됨.

## A-P4-3. KR 전력 프록시는 yfinance에서 정상 조회됨 — 스킵 불필요

- KR 전력 프록시(백필 당시 117460.KS, 2026-07-02 사용자 확정 후 487240.KS로 교체됨 —
  docs/07 해결)는 yfinance에서 데이터가 나옴 → 섹터 스킵 없이 KR 6개 섹터 전부 백필 성공.
- 단, 일부 KR ETF는 상장 이력이 짧아 (로봇 445290: 2023-11 상장, 전력 487240: 2024-07 상장 등)
  백필 시작일이 섹터마다 다름 (KR 최초 저장일 2024-04-22, 워밍업 제외 후). 전력은 특히
  이력이 짧아(약 2년) z-score 워밍업(504거래일=2년)을 겨우 채우는 수준 — 초기 신호는
  변동성이 클 수 있음을 감안할 것.

## A-P4-4. ECOS 키 없으면 KR 금리는 미국 금리로 대체 + degraded

- ECOS 키 부재/장애 시 KR의 L축 입력(국고3Y/10Y)을 FRED DGS2/DGS10으로 대체하고
  `macro_snapshots.payload.degraded = true` 기록. 가정 A7(글로벌 축은 미국 기준)에
  기대어 방향성은 근사되지만 KR 고유 금리 사이클은 반영 못 함 — 키 투입 권장.
- yfinance에는 한국 국채 수익률 시계열이 없어 "yfinance 폴백"은 불가(지시문과 동일 판단).

## A-P4-5. `signal_changed`/알림의 "신호 변화" 정의 = 스탠스(LONG/CASH) 전환

- 표시 신호(hold/keep/cash)는 임계값 재확인 때문에 hold↔keep로 자주 진동함.
  대시보드의 `signal_changed`와 알림 생성 기준은 **스탠스 전환**(LONG↔CASH)으로 통일
  — "신호 자체가 바뀔 때만 발송"(CLAUDE.md 알림 원칙)과 정합.
- LONG→CASH만 `immediate=true`, CASH→LONG 및 국면 전환은 다이제스트(false).

## A-P4-6. 백필은 z-score 워밍업 252거래일 제외 저장

- 초기 252거래일은 z-score 표본 부족으로 점수가 사실상 중립 노이즈 → 백테스트(P3)
  평가 기준과 동일하게 백필 저장에서 제외. (`--days 1200` 기본이면 약 2.3년치 저장)

## A-P4-7. 뉴스 감성 — 키 없으면 중립, 초기엔 게이트 통과가 드묾

- ALPHAVANTAGE_API_KEY 없으면 뉴스 파트 전체 스킵 → 엔진이 news=0.5(중립) 처리.
- 키가 있어도 조회는 최근 30일(time_from)이라, 3중 게이트의 63일 롤링 std 표본이
  쌓이기 전 초기 몇 주는 사실상 중립으로 동작 (설계상 안전한 방향의 보수성).
- 호출량: 섹터당 1콜 = 일 6콜 (무료 25콜/일 한도 내).

## A-P4-8. 뉴스 요약 = claude-haiku-4-5-20251001, 표시용 전용

- `anthropic` 패키지는 요약 함수 안에서 지연 import. 키 없음/패키지 없음/호출 실패
  모두 파이프라인 성공에 영향 없음 (경고 로그만). 신호 계산 경로에 LLM 0회 유지.

## A-P4-9. /api/v1/jobs/run은 API_KEY 미설정 시 403

- STATE.md의 "(키 필수)"를 "API_KEY가 설정돼 있고 헤더가 일치할 때만 실행 가능"으로
  해석. 미설정(로컬 개발) 상태에서는 원격 트리거 자체를 막고 CLI 실행을 안내.

## 검증 결과 요약 (2026-07-02 실행)

- pytest: 46 passed (기존 엔진 21 + store 10 + API 10 + 파이프라인 유닛 5)
- E2E US `--backfill` (키 전무, yfinance+FRED CSV): 6섹터 3,432행 저장, degraded=false
- E2E KR `--backfill` (yfinance .KS 폴백): 6섹터 3,180행 저장, degraded=true (ECOS 없음)
- 증분 실행 US: 섹터당 1행 upsert, 허위 알림 0건
- API 스모크 (uvicorn+curl): /health, dashboard, history, detail, regime/history,
  notifications pending/ack, jobs/run(403), 404 검증 — 전부 계약 일치
