import Foundation
import BackgroundTasks

// BGAppRefreshTask 기반 백그라운드 갱신.
// - 앱 실행 시 register(), 백그라운드 진입 시 schedule() (최소 4시간 간격)
// - 실행 시 dashboard + notifications/pending 폴링 → NotificationService 처리

enum BackgroundRefresh {
    static let taskIdentifier = "com.personal.richsignal.refresh"
    private static let minimumInterval: TimeInterval = 4 * 60 * 60

    /// 앱 시작 시 1회 등록 (@main init에서 호출)
    static func register() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: taskIdentifier, using: nil) { task in
            guard let refreshTask = task as? BGAppRefreshTask else {
                task.setTaskCompleted(success: false)
                return
            }
            handle(refreshTask)
        }
    }

    /// 다음 실행 예약 (이미 예약돼 있으면 교체)
    static func schedule() {
        let request = BGAppRefreshTaskRequest(identifier: taskIdentifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: minimumInterval)
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            // 시뮬레이터 등 미지원 환경에서는 조용히 무시
        }
    }

    private static func handle(_ task: BGAppRefreshTask) {
        schedule()   // 다음 사이클 예약

        let job = Task {
            let client = APIClient.current
            var success = true
            do {
                _ = try await client.dashboard()
                AppSettings.lastSyncAt = Date()
                if AppSettings.notificationsEnabled {
                    let pending = try await client.pendingNotifications()
                    await NotificationService.shared.process(pending.items, using: client)
                }
            } catch {
                success = false
            }
            task.setTaskCompleted(success: success)
        }

        task.expirationHandler = {
            job.cancel()
            task.setTaskCompleted(success: false)
        }
    }

    /// 포그라운드 진입 시에도 동일 폴링 수행 (앱을 직접 열었을 때 알림 예약 갱신)
    static func foregroundPoll() async {
        let client = APIClient.current
        guard AppSettings.notificationsEnabled,
              let pending = try? await client.pendingNotifications() else { return }
        await NotificationService.shared.process(pending.items, using: client)
    }
}
