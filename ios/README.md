# RichSignal — 개인용 매매신호 iOS 앱

6섹터(반도체/로봇/전력/헬스케어/금/국채) × 2시장(KR/US) 매매신호 대시보드.
자동매매 아님 — 신호만 표시하고 매매는 수동. 개인용 사이드로딩 전용(앱스토어 배포 안 함).

## 빌드 & 실행 (Xcode 있는 머신에서)

```bash
# 1. XcodeGen 설치 (최초 1회)
brew install xcodegen

# 2. 프로젝트 생성 (ios/ 디렉토리에서)
cd ios
xcodegen generate

# 3. Xcode에서 열기
open RichSignal.xcodeproj
```

4. Xcode에서:
   - 타깃 RichSignal → Signing & Capabilities → 본인 Apple ID의 Personal Team 선택
   - 시뮬레이터 또는 실기기 선택 후 ⌘R 실행
5. **모의 데이터 모드가 기본 ON** 이므로 백엔드 없이 바로 전체 화면 확인 가능
   (설정 탭에서 서버 URL/API 키 입력 후 모의 데이터 모드를 끄면 실서버 연동)

실기기 사이드로딩 시 무료 Personal Team 프로비저닝은 7일마다 재서명 필요.

## 파일 구조

```
ios/
├── project.yml                  # XcodeGen 스펙 (타깃/Info.plist/BGTask 설정)
└── RichSignal/
    ├── RichSignalApp.swift      # @main, BGTask 등록, 알림 권한 요청, 탭 루트
    ├── Models/
    │   └── APIModels.swift      # STATE.md API 계약의 Codable 모델 + 열거형
    │                            #   (MarketCode/SectorCode/SignalType/RegimeCode)
    ├── Services/
    │   ├── AppSettings.swift    # UserDefaults 설정 (서버 URL, API 키, 모의 모드,
    │   │                        #   다이제스트 시각, 알림 on/off)
    │   ├── APIClient.swift      # async/await URLSession + X-API-Key,
    │   │                        #   mockMode면 MockDataService로 스위칭
    │   ├── MockDataService.swift# 시드 고정 모의 데이터 (12카드 중 2개 신호 변경,
    │   │                        #   180일 히스토리에 스탠스 전환 3~4회)
    │   ├── NotificationService.swift # 로컬 알림: 즉시(현금보유 전환) / 다이제스트 묶음
    │   └── BackgroundRefresh.swift   # BGAppRefreshTask (최소 4시간 간격 폴링)
    └── Views/
        ├── DashboardView.swift  # ① 신호 변경 → ② 거시 국면 배지 → ③ 섹터 카드
        ├── SectorDetailView.swift # 신호/국면방향 → T/V/M 드릴다운 → 180일 차트 → 뉴스
        ├── SettingsView.swift   # 서버/알림/다이제스트 시각/마지막 동기화
        └── Components.swift     # SignalBadge, RegimeBadge, ComponentBars 등
```

## 신호 표기 (색약 대응: 색 + 아이콘 항상 병용)

| 신호 | 색 | 아이콘 | 의미 |
|---|---|---|---|
| hold | 초록 | ▲ arrowtriangle.up.fill | 보유 |
| cash | 빨강 | ■ square.fill | 현금보유 |
| keep | 주황 | ▶ play.fill | 유지 |

국면 배지: G 이상적 성장 / R 경기 과열 / T 긴축 스트레스 / F 위험회피(안전자산)

## 백엔드 연동

- STATE.md "API 계약" 섹션의 엔드포인트를 그대로 사용 (`/api/v1/dashboard` 등)
- 인증: 설정에 입력한 API 키를 `X-API-Key` 헤더로 전송 (빈 값이면 헤더 생략)
- `http://localhost` 예외가 Info.plist(ATS)에 포함되어 있어 로컬 FastAPI로 바로 테스트 가능
- 백그라운드 갱신: `com.personal.richsignal.refresh` (BGAppRefreshTask, 최소 4시간 간격).
  실행 시 dashboard + notifications/pending 폴링 후 로컬 알림 예약/발송 → ack POST

## 이 머신(Xcode 없음)에서의 검증 상태

- 전체 `.swift` 파일 `swiftc -parse` 통과 (문법 검증)
- Models/Services(BackgroundRefresh 제외)는 macOS SDK로 `swiftc -typecheck`까지 통과
- MockDataService는 macOS에서 실제 실행해 데이터 형태 검증 완료
- SwiftUI 뷰의 iOS 전용 API는 Xcode 빌드로 최종 확인 필요 (AGENT_NOTES.md 참고)
