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
    }
}
