# 배포 가이드 — Railway + Supabase (신규 프로젝트, KATT와 완전 분리)

> 소요 시간 약 20~30분. 모두 무료 티어로 시작 가능 (Railway는 Hobby $5/월 권장).

## 1. Supabase 새 프로젝트

1. https://supabase.com → 기존 계정 로그인 → **New Project** (KATT와 같은 계정이어도 별도 프로젝트)
   - 이름: `richman-signals`, 리전: Northeast Asia (Seoul)
2. 생성 후 **SQL Editor** → `backend/app/db/migrations/001_init.sql` 내용 붙여넣고 실행
3. **Project Settings → API** 에서 복사:
   - `Project URL` → 환경변수 `SUPABASE_URL`
   - `service_role` 키 → `SUPABASE_SERVICE_KEY` (개인용 백엔드 전용이므로 service_role 사용, 절대 앱에 넣지 말 것)

## 2. API 키 발급 (무료)

| 키 | 발급처 | 소요 |
|---|---|---|
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | 1분 |
| `ECOS_API_KEY` | https://ecos.bok.or.kr → 인증키 신청 | 몇 시간 내 승인 |
| `ALPHAVANTAGE_API_KEY` | https://www.alphavantage.co/support/#api-key | 1분 |
| `KIS_APP_KEY/SECRET` | 기존 KIS Developers 앱 키 재사용 (모의투자 아닌 실전 키) | 보유 중 |
| `ANTHROPIC_API_KEY` | 뉴스 요약용 (선택) — 없으면 요약만 생략됨 | 보유 중 |
| `API_KEY` | 직접 생성: `openssl rand -hex 24` — iOS 앱과 서버 공유 비밀 | 즉시 |

> 키가 하나도 없어도 파이프라인은 돌아감 (yfinance + FRED CSV 폴백, 뉴스/요약 생략).
> ECOS 키 승인 전까지 KR 국면의 금리 축은 미국 금리로 대체되고 macro_snapshots에 degraded 표시.

## 3. Railway 새 프로젝트

1. https://railway.app → **New Project → Deploy from GitHub repo** (이 저장소를 GitHub 비공개 저장소로 푸시했다면) 또는 **Empty Project → CLI 배포**
2. CLI 배포 방법:
   ```bash
   npm i -g @railway/cli   # 또는 brew install railway
   cd backend
   railway login
   railway init            # 새 프로젝트 richman-signals
   railway up              # Dockerfile/Nixpacks 자동 감지
   ```
3. **Variables** 에 2번의 환경변수 전부 등록 (+ `PORT`는 Railway가 자동 주입)
4. **Settings → Networking → Generate Domain** → 도메인 확보 (예: `richman-signals.up.railway.app`)
   — 이 URL을 iOS 앱 설정 화면의 "서버 URL"에 입력

시작 커맨드 (Nixpacks 자동 감지 실패 시 Settings → Deploy → Start Command):
```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## 4. 배치 스케줄 (Railway Cron)

Railway 프로젝트에 **Cron 서비스 2개** 추가 (New → Cron Job, 같은 저장소/이미지 사용):

| 잡 | Cron (UTC) | 커맨드 |
|---|---|---|
| 한국장 마감 후 | `50 6 * * 1-5` (= KST 15:50 월~금) | `python -m app.jobs.daily_pipeline --market KR` |
| 미국장 마감 후 | `10 21 * * 1-5` (= KST 06:10 화~토) | `python -m app.jobs.daily_pipeline --market US` |

> Railway cron은 UTC 기준. 미국 서머타임에 따라 마감 시각이 1시간 이동하지만
> 06:10 KST 실행은 겨울에도 마감(06:00 KST) 이후라 안전.

## 5. 초기 데이터 적재 (1회)

배포 후 과거 이력을 한 번에 채움 (앱의 6개월 그래프용):
```bash
railway run python -m app.jobs.daily_pipeline --market US --backfill
railway run python -m app.jobs.daily_pipeline --market KR --backfill
```

## 6. 동작 확인

```bash
curl -H "X-API-Key: <API_KEY>" https://<도메인>/health
curl -H "X-API-Key: <API_KEY>" https://<도메인>/api/v1/dashboard | python3 -m json.tool | head -40
```

## 로컬 개발 (배포 없이)

```bash
cd backend
.venv/bin/python -m app.jobs.daily_pipeline --market US --backfill   # SQLite(richman.db)에 저장
.venv/bin/uvicorn app.main:app --reload                              # http://localhost:8000
```
iOS 앱 설정에서 서버 URL을 `http://<맥의 로컬 IP>:8000` 으로 지정하면 실기기에서도 접속 가능.
