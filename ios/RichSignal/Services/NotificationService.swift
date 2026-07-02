import Foundation
import UserNotifications

// 로컬 알림 처리 (CLAUDE.md 알림 원칙):
// - immediate=true (현금보유 전환 등) → 즉시 배너
// - 나머지 → 설정된 다이제스트 시각(다음 도래 시각)에 1건으로 묶어 예약
// - 예약/표시 처리 후 서버에 ack POST (재발송 방지)

final class NotificationService {
    static let shared = NotificationService()

    private let digestIdentifier = "richsignal.digest"
    private let digestLinesKey = "digest.pendingLines"
    private let digestSlotKey = "digest.slot"

    private var center: UNUserNotificationCenter { .current() }

    // MARK: 권한

    @discardableResult
    func requestAuthorization() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    // MARK: pending 이벤트 처리

    /// 서버(또는 모의 데이터)의 pending 알림을 로컬 알림으로 변환하고 ack
    func process(_ items: [PendingNotification], using client: SignalDataProviding) async {
        guard AppSettings.notificationsEnabled, !items.isEmpty else { return }

        let immediateItems = items.filter(\.immediate)
        let digestItems = items.filter { !$0.immediate }

        for item in immediateItems {
            scheduleImmediate(item)
        }
        if !digestItems.isEmpty {
            scheduleDigest(digestItems)
        }

        // 예약 완료 = 표시 보장으로 간주하고 ack (AGENT_NOTES 참고)
        _ = try? await client.ackNotifications(ids: items.map(\.id))
    }

    // MARK: 즉시 알림

    private func scheduleImmediate(_ item: PendingNotification) {
        let content = UNMutableNotificationContent()
        content.title = item.title
        content.body = item.body
        content.sound = .default
        content.interruptionLevel = .timeSensitive
        let request = UNNotificationRequest(
            identifier: "richsignal.immediate.\(item.id)",
            content: content,
            trigger: nil   // 즉시 전달
        )
        center.add(request)
    }

    // MARK: 다이제스트

    /// 다음 다이제스트 시각 (설정 시각이 이미 지났으면 내일)
    func nextDigestDate(after reference: Date = Date()) -> Date {
        var components = Calendar.current.dateComponents([.year, .month, .day], from: reference)
        components.hour = AppSettings.digestHour
        components.minute = AppSettings.digestMinute
        components.second = 0
        let todaySlot = Calendar.current.date(from: components) ?? reference
        if todaySlot > reference { return todaySlot }
        return Calendar.current.date(byAdding: .day, value: 1, to: todaySlot) ?? todaySlot
    }

    /// 다이제스트 항목을 UserDefaults에 누적하고, 하나의 알림으로 (재)예약
    private func scheduleDigest(_ items: [PendingNotification]) {
        let defaults = UserDefaults.standard
        let slot = nextDigestDate()
        let slotString = ISO8601DateFormatter().string(from: slot)

        // 슬롯이 바뀌었으면(이전 다이제스트 시각이 지났으면) 누적 항목 초기화
        var lines = defaults.stringArray(forKey: digestLinesKey) ?? []
        if defaults.string(forKey: digestSlotKey) != slotString {
            lines = []
        }
        for item in items {
            let line = "\(item.title) — \(item.body)"
            if !lines.contains(line) {
                lines.append(line)
            }
        }
        defaults.set(lines, forKey: digestLinesKey)
        defaults.set(slotString, forKey: digestSlotKey)

        let content = UNMutableNotificationContent()
        content.title = "리치시그널 다이제스트 (\(lines.count)건)"
        content.body = lines.map { "• \($0)" }.joined(separator: "\n")
        content.sound = .default

        let triggerComponents = Calendar.current.dateComponents(
            [.year, .month, .day, .hour, .minute], from: slot)
        let trigger = UNCalendarNotificationTrigger(dateMatching: triggerComponents, repeats: false)

        // 동일 identifier로 add → 기존 예약을 교체 (항목 누적 반영)
        let request = UNNotificationRequest(identifier: digestIdentifier, content: content, trigger: trigger)
        center.add(request)
    }
}
