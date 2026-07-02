import SwiftUI

// 앱 설정.
// - 뷰: `@AppStorage(AppSettings.Key.xxx)` 로 직접 바인딩 (SwiftUI 갱신 보장)
// - 서비스 계층: `AppSettings.xxx` 정적 접근자로 동일 UserDefaults 값을 읽음
//   (@AppStorage 를 ObservableObject 안에 넣으면 objectWillChange 가 발화되지 않는
//    SwiftUI 제약이 있어, 키 공유 방식으로 래핑)

enum AppSettings {
    enum Key {
        static let baseURL = "baseURL"
        static let apiKey = "apiKey"
        static let mockMode = "mockMode"
        static let digestHour = "digestHour"
        static let digestMinute = "digestMinute"
        static let notificationsEnabled = "notificationsEnabled"
        static let lastSyncAt = "lastSyncAt"
    }

    private static var defaults: UserDefaults { .standard }

    /// 백엔드 베이스 URL (예: "http://localhost:8000") — 기본 빈 문자열
    static var baseURL: String {
        get { defaults.string(forKey: Key.baseURL) ?? "" }
        set { defaults.set(newValue, forKey: Key.baseURL) }
    }

    /// X-API-Key 헤더 값
    static var apiKey: String {
        get { defaults.string(forKey: Key.apiKey) ?? "" }
        set { defaults.set(newValue, forKey: Key.apiKey) }
    }

    /// 모의 데이터 모드 (기본 true — 백엔드 없이 즉시 확인 가능)
    static var mockMode: Bool {
        get { defaults.object(forKey: Key.mockMode) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Key.mockMode) }
    }

    /// 다이제스트 발송 시각 (기본 07:30)
    static var digestHour: Int {
        get { defaults.object(forKey: Key.digestHour) as? Int ?? 7 }
        set { defaults.set(newValue, forKey: Key.digestHour) }
    }

    static var digestMinute: Int {
        get { defaults.object(forKey: Key.digestMinute) as? Int ?? 30 }
        set { defaults.set(newValue, forKey: Key.digestMinute) }
    }

    /// 알림 사용 여부 (기본 true)
    static var notificationsEnabled: Bool {
        get { defaults.object(forKey: Key.notificationsEnabled) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Key.notificationsEnabled) }
    }

    /// 마지막 동기화 시각 (없으면 nil)
    static var lastSyncAt: Date? {
        get {
            let t = defaults.double(forKey: Key.lastSyncAt)
            return t > 0 ? Date(timeIntervalSince1970: t) : nil
        }
        set { defaults.set(newValue?.timeIntervalSince1970 ?? 0, forKey: Key.lastSyncAt) }
    }
}
