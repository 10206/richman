# 배포 가이드 — Railway (볼륨 + SQLite, KATT와 완전 분리)

> 소요 시간 약 15~20분. Railway Hobby 플랜(월 $5) 하나만 있으면 됨 — 별도 DB 서비스 불필요.
> Supabase는 쓰지 않음 (2026-07-02 결정, 근거는 docs/00-ASSUMPTIONS.md A9).

## 아키텍처

Railway 프로젝트 하나에 서비스 3개:

| 서비스 | 역할 | 볼륨 |
|---|---|---|
| **richman-api** | FastAPI 상시 실행. iOS 앱이 여기 접속. `/api/v1/jobs/run` 호출 시 배치 실행 | O (`/data`) |
| **richman-cron-kr** | 매일 15:50 KST에 API를 호출만 함 (자체 로직/DB 없음) | X |
| **richman-cron-us** | 매일 06:10 KST에 API를 호출만 함 | X |

> Railway는 볼륨을 서비스당 1개만 허용하고 서비스 간 공유가 안 됩니다(2026-07 기준 플랫폼
> 제약). 그래서 DB에 실제로 쓰는 로직은 볼륨을 가진 `richman-api` 안에서만 실행되도록 하고,
> 크론 서비스는 그 API를 HTTP로 호출만 하는 얇은 트리거로 둡니다. 이미 구현된
> `POST /api/v1/jobs/run` 엔드포인트를 그대로 재사용하므로 추가 코드는 필요 없습니다.

## 1. API 키 발급 (전부 선택, 없어도 동작)

| 키 | 발급처 | 소요 |
|---|---|---|
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | 1분 |
| `ECOS_API_KEY` | https://ecos.bok.or.kr → 인증키 신청 | 몇 시간 내 승인 |
| `ALPHAVANTAGE_API_KEY` | https://www.alphavantage.co/support/#api-key | 1분 |
| `KIS_APP_KEY/SECRET` | 기존 KIS Developers 앱 키 재사용 (모의투자 아닌 실전 키) | 보유 중 |
| `ANTHROPIC_API_KEY` | 뉴스 요약용 (선택) — 없으면 요약만 생략됨 | 보유 중 |
| `API_KEY` | 직접 생성: `openssl rand -hex 24` — **필수**, 아래 3개 서비스가 전부 공유 | 즉시 |

> 키가 하나도 없어도 파이프라인은 돌아감 (yfinance + FRED CSV 폴백, 뉴스/요약 생략).
> `API_KEY`만은 필수입니다 — 없으면 `/api/v1/jobs/run`이 막혀서 크론이 동작하지 않습니다.
> ECOS 키 승인 전까지 KR 국면의 금리 축은 미국 금리로 대체되고 macro_snapshots에 degraded 표시.

## 2. richman-api 서비스 생성 (볼륨 포함)

1. https://railway.app → GitHub으로 로그인 → **New Project → Deploy from GitHub repo**
   → `10206/richman` 선택 (이미 코드가 푸시돼 있음)
2. 서비스 **Settings → Deploy**:
   - Root Directory: `/backend`
   - Custom Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. **Settings → Volumes → New Volume**:
   - Mount Path: `/data`
4. **Variables** 탭에 등록:
   - `DB_PATH=/data/richman.db`
   - `API_KEY=<1번에서 만든 값>`
   - (선택) `FRED_API_KEY`, `ECOS_API_KEY`, `ALPHAVANTAGE_API_KEY`, `KIS_APP_KEY`, `KIS_APP_SECRET`, `ANTHROPIC_API_KEY`
   - `PORT`은 Railway가 자동 주입하므로 직접 설정 안 해도 됨
5. **Settings → Networking → Generate Domain** → 예: `richman-api.up.railway.app`
   — 이 URL이 iOS 앱 설정 화면의 "서버 URL" + 아래 크론 서비스들이 호출할 대상

## 3. 크론 서비스 2개 생성 (curl만 실행하는 경량 서비스)

같은 프로젝트 안에서 **New → Docker Image**로 2번 반복:

1. Image name: `curlimages/curl:latest`
2. 서비스 이름을 `richman-cron-kr` (두 번째는 `richman-cron-us`)로 변경
3. **Settings → Deploy → Custom Start Command**:
   ```bash
   # richman-cron-kr
   curl -sf -X POST -H "X-API-Key: $API_KEY" --max-time 120 "https://<richman-api 도메인>/api/v1/jobs/run?market=KR"
   ```
   ```bash
   # richman-cron-us
   curl -sf -X POST -H "X-API-Key: $API_KEY" --max-time 120 "https://<richman-api 도메인>/api/v1/jobs/run?market=US"
   ```
4. **Settings → Cron Schedule**:

   | 서비스 | Cron (UTC) | 의미 |
   |---|---|---|
   | richman-cron-kr | `50 6 * * 1-5` | KST 15:50 월~금 (한국장 마감 후) |
   | richman-cron-us | `10 21 * * 1-5` | KST 06:10 화~토 (미국장 마감 후) |

5. **Variables**에 `API_KEY` 등록 (1번과 동일한 값 — richman-api와 공유하는 비밀값)

> Cron Schedule이 설정된 서비스는 상시 실행되지 않고, 스케줄된 시각에 컨테이너를 띄워
> Start Command를 한 번 실행하고 종료합니다. Railway cron은 UTC 기준이며 최소 실행 간격은
> 5분이지만 여긴 하루 1회라 무관. 미국 서머타임에 따라 마감 시각이 최대 1시간 이동해도
> 06:10 KST 실행은 겨울에도 마감(06:00 KST) 이후라 안전.

## 4. 초기 데이터 적재 (1회, 대시보드/CLI 불필요)

배포 직후 터미널에서 curl 두 번이면 끝 — 6개월~수년치 이력을 한 번에 채웁니다:

```bash
curl -X POST -H "X-API-Key: <API_KEY>" \
  "https://<richman-api 도메인>/api/v1/jobs/run?market=US&backfill=true"
curl -X POST -H "X-API-Key: <API_KEY>" \
  "https://<richman-api 도메인>/api/v1/jobs/run?market=KR&backfill=true"
```
각 호출은 로컬 기준 약 5~10초 소요 (외부 API 키를 설정했다면 뉴스/요약 단계 때문에 더 걸릴 수 있음).

## 5. 동작 확인

```bash
curl -H "X-API-Key: <API_KEY>" https://<richman-api 도메인>/health
curl -H "X-API-Key: <API_KEY>" https://<richman-api 도메인>/api/v1/dashboard | python3 -m json.tool | head -40
```
다음 날 크론이 실행된 후 richman-cron-kr/us 서비스의 **Deployments** 탭에서 로그(curl 응답)를
확인하면 정상 동작 여부를 알 수 있습니다.

## 로컬 개발 (배포 없이)

```bash
cd backend
.venv/bin/python -m app.jobs.daily_pipeline --market US --backfill   # SQLite(richman.db)에 저장
.venv/bin/uvicorn app.main:app --reload                              # http://localhost:8000
```
iOS 앱 설정에서 서버 URL을 `http://<맥의 로컬 IP>:8000` 으로 지정하면 실기기에서도 접속 가능.

## 참고: Supabase로 되돌리고 싶다면

`app/db/store.py`의 `SupabaseStore`는 코드에 그대로 남아 있습니다. `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY` 환경변수를 richman-api 서비스에 설정하면 `get_store()`가 자동으로
Supabase를 우선 사용합니다 (`DB_PATH`/볼륨은 무시됨). 마이그레이션은
`backend/app/db/migrations/001_init.sql`을 Supabase SQL Editor에서 실행하면 됩니다.
