# P5 구현 중 가정/판단 기록

Xcode 미설치 환경에서 작성됨 — Xcode 빌드로 최종 확인 전까지의 가정 목록.

## API 계약 해석

1. **snake_case 숫자 세그먼트**: `JSONDecoder.convertFromSnakeCase`는
   `y_long_chg_63d` → `yLongChg63D`, `score_delta_1d` → `scoreDelta1D` 로 변환함
   (`.capitalized` 가 `"63d"` → `"63D"`). macOS에서 실제 디코딩 테스트로 확인 후
   프로퍼티명을 이에 맞춤. 백엔드가 키 이름을 바꾸면 여기가 첫 번째 의심 지점.
2. **news_items.sentiment 타입**: 계약에 타입 명시가 없어 `Double`(음수=부정,
   양수=긍정, ±0.15 안쪽=중립)로 가정. 백엔드가 문자열 라벨("positive" 등)을 주면
   `NewsItem.sentiment` 디코딩이 실패하므로 P4와 맞춰야 함.
3. **local_trend 값**: 표기 미확정이라 `String`으로 받고 `LocalTrendDisplay`에서
   영어(bull/bear/neutral 등)/한국어 모두 한국어 라벨로 변환. 미지의 값은 원문 표시.
4. **pending 알림의 sector**: 국면 변경 이벤트는 특정 섹터가 없다고 보고
   `SectorCode?` (옵셔널)로 선언.
5. **macro_raw**: 계약상 `?` 표시가 없는 필드(y_short 등)도 시장/섹터에 따라
   빠질 수 있다고 보고 전부 옵셔널로 선언 (nil이면 상세 화면에서 행 생략).
6. **score/prev_signal/score_delta_1d**: 운영 첫날 등 이전 값이 없을 수 있어
   `prevSignal`, `scoreDelta1D`는 옵셔널.

## 설계 판단

7. **@AppStorage 래핑 방식**: `@AppStorage`를 ObservableObject 안에 두면
   objectWillChange가 발화되지 않는 SwiftUI 제약이 있어, 뷰는
   `@AppStorage(AppSettings.Key.xxx)` 직접 선언, 서비스는 `AppSettings` 정적
   접근자로 같은 UserDefaults 키를 읽는 구조로 래핑함.
8. **ack 시점**: "표시 후 ack"를 "로컬 알림 예약 완료 = 표시 보장"으로 해석해
   예약 직후 ack POST. (예약된 알림은 앱 삭제 전까지 iOS가 표시하므로
   유실 가능성은 다이제스트 예약 후 앱 삭제 정도뿐.)
9. **다이제스트 누적**: 여러 번 폴링해도 다이제스트 알림은 identifier 고정
   (`richsignal.digest`)으로 1건 유지, 항목은 UserDefaults에 누적 후 본문 재구성.
   다이제스트 시각(슬롯)이 지나면 누적 목록 초기화.
10. **점수 delta 색상**: 한국 증시 관행(상승=빨강)이 아니라 신호 색 체계와
    일관되게 상승=초록/하락=빨강 사용 (색+화살표 병용이라 색약 대응은 유지).
11. **표시 신호 규칙**: docs/02 §4의 3구간 규칙을 "표시 신호는 구간 즉시 반영,
    스탠스는 confirm일+히스테리시스"로 해석 (모의 데이터 생성에 사용).
    실서버 모드에서는 서버가 준 signal/stance를 그대로 표시하므로 영향 없음.
12. **차트 임계값 미표시**: enter/exit 임계값은 API로 내려오지 않아
    차트에 기준선을 그리지 않음 (docs 상수를 하드코딩하면 백엔드 파라미터
    변경 시 어긋나므로).
13. **모의 데이터 신호 변경 카드**: US 반도체(보유→현금보유, 즉시 알림 시나리오),
    KR 금(유지→보유, 다이제스트 시나리오) 2건을 고정 연출하고 나머지 10개 카드는
    오늘 신호 변경이 없도록 마지막 날 점수를 정렬. pending 알림 3건(즉시 1 +
    다이제스트 2)과 스토리가 일치함.

## 검증 커버리지 한계

14. `swiftc -parse`(문법) 전 파일 통과. Models/Services 5개 파일은 macOS SDK로
    `-typecheck`까지 통과했고 MockDataService는 실행 검증까지 완료.
    Views/BackgroundRefresh의 iOS 전용 API(Charts 마커, insetGrouped,
    navigationBarTitleDisplayMode, BGTaskScheduler 등)는 타입 검증 못 함 —
    Xcode 첫 빌드에서 사소한 수정이 나올 수 있는 영역.
15. project.yml은 XcodeGen 미설치로 `xcodegen generate` 실행 검증 못 함
    (스펙 문법은 XcodeGen 공식 문서 기준으로 작성).
