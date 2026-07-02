import SwiftUI

@main
struct RichSignalApp: App {
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // BGTask 핸들러는 앱 시작 직후(didFinishLaunching 이전 단계)에 등록해야 함
        BackgroundRefresh.register()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .task {
                    await NotificationService.shared.requestAuthorization()
                    await BackgroundRefresh.foregroundPoll()
                }
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                BackgroundRefresh.schedule()
            }
        }
    }
}

struct RootView: View {
    var body: some View {
        TabView {
            NavigationStack {
                DashboardView()
            }
            .tabItem {
                Label("대시보드", systemImage: "chart.bar.fill")
            }

            NavigationStack {
                SettingsView()
            }
            .tabItem {
                Label("설정", systemImage: "gearshape.fill")
            }
        }
        // 앱 강조색 = 로고 연두 (AccentColor 에셋: 라이트 짙은 연두 / 다크 밝은 연두).
        // 색상 스킴 자체는 시스템(아이폰) 설정을 그대로 따른다 — 강제하지 않음.
        .tint(Color("AccentColor"))
    }
}
