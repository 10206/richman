# 프로젝트 진행 상태 (자동 갱신)

> 이 파일은 Claude가 장시간 자율 작업 중 진행 상황을 추적하기 위해 유지합니다.
> 컨텍스트가 요약되어도 이 파일을 읽으면 어디까지 했는지 알 수 있습니다.

## 페이즈

- [x] P1. 설계 문서 (docs/00~03)
- [ ] P2. 시그널 엔진 — 순수 로직 (backend/app/engine) + 단위 테스트
- [ ] P3. 백테스트 (실데이터, stooq/FRED) → docs/04 리포트, 임계값 튜닝
- [ ] P4. 데이터 클라이언트 (KIS/ECOS/FRED/뉴스) + FastAPI + Supabase 스키마 + 배치 잡
- [ ] P5. iOS SwiftUI 앱 (ios/) — XcodeGen 프로젝트
- [ ] P6. 배포/설치 가이드 (docs/05~06) + 사용자 판단 필요 항목 (docs/07)

## 환경 제약 (확인됨)

- Python 3.13 사용 가능, 네트워크 OK (FRED/ECOS/stooq 접근 확인)
- **Xcode 미설치** (CommandLineTools만 있음) → 시뮬레이터 빌드 검증 불가.
  Swift 문법 검증(`swiftc -parse`) + XcodeGen 프로젝트 + 설치 가이드로 대체.
- 기존 KIS API / KR-FinBert-SC 코드는 이 머신에서 참조 불가 → 공식 스펙 기반 신규 작성.
- ECOS/FRED/KIS API 키 없음 → 백테스트는 키 불필요한 소스(fredgraph CSV, stooq) 사용,
  프로덕션 코드는 환경변수로 키 주입.

## 현재 작업

P1 설계 문서 작성 중.
