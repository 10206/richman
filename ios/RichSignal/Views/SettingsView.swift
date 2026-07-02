import SwiftUI

struct SettingsView: View {
    @AppStorage(AppSettings.Key.baseURL) private var baseURL = ""
    @AppStorage(AppSettings.Key.apiKey) private var apiKey = ""
    @AppStorage(AppSettings.Key.mockMode) private var mockMode = true
    @AppStorage(AppSettings.Key.notificationsEnabled) private var notificationsEnabled = true
    @AppStorage(AppSettings.Key.digestHour) private var digestHour = 7
    @AppStorage(AppSettings.Key.digestMinute) private var digestMinute = 30
    @AppStorage(AppSettings.Key.lastSyncAt) private var lastSyncAt = 0.0

    @State private var healthMessage: String?
    @State private var isTestingConnection = false

    var body: some View {
        Form {
            serverSection
            notificationSection
            statusSection
        }
        .navigationTitle("설정")
    }

    // MARK: 서버

    private var serverSection: some View {
        Section {
            TextField("서버 URL (예: http://localhost:8000)", text: $baseURL)
                .keyboardType(.URL)
                .textContentType(.URL)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)

            SecureField("API 키 (X-API-Key)", text: $apiKey)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)

            Toggle("모의 데이터 모드", isOn: $mockMode)

            Button {
                Task { await testConnection() }
            } label: {
                HStack {
                    Text("연결 테스트")
                    Spacer()
                    if isTestingConnection {
                        ProgressView()
                    } else if let healthMessage {
                        Text(healthMessage)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .disabled(isTestingConnection || baseURL.isEmpty)
        } header: {
            Text("서버")
        } footer: {
            Text("모의 데이터 모드를 켜면 백엔드 없이 시드 고정 예시 데이터로 전체 화면을 확인할 수 있습니다.")
        }
    }

    // MARK: 알림

    private var notificationSection: some View {
        Section {
            Toggle("알림 사용", isOn: $notificationsEnabled)
                .onChange(of: notificationsEnabled) { _, enabled in
                    if enabled {
                        Task { await NotificationService.shared.requestAuthorization() }
                    }
                }

            DatePicker("다이제스트 시각",
                       selection: digestTimeBinding,
                       displayedComponents: .hourAndMinute)
                .disabled(!notificationsEnabled)
        } header: {
            Text("알림")
        } footer: {
            Text("현금보유 전환은 즉시 알림, 그 외(보유 전환·국면 변경)는 설정한 시각에 다이제스트로 묶어 전달합니다.")
        }
    }

    // MARK: 상태

    private var statusSection: some View {
        Section("상태") {
            HStack {
                Text("마지막 동기화")
                Spacer()
                Text(lastSyncText)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Text("데이터 소스")
                Spacer()
                Text(mockMode ? "모의 데이터" : "실서버")
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: 헬퍼

    /// digestHour/digestMinute(@AppStorage Int) ↔ DatePicker(Date) 브리지
    private var digestTimeBinding: Binding<Date> {
        Binding {
            Calendar.current.date(
                from: DateComponents(hour: digestHour, minute: digestMinute)
            ) ?? Date()
        } set: { newValue in
            let c = Calendar.current.dateComponents([.hour, .minute], from: newValue)
            digestHour = c.hour ?? 7
            digestMinute = c.minute ?? 30
        }
    }

    private var lastSyncText: String {
        guard lastSyncAt > 0 else { return "없음" }
        let date = Date(timeIntervalSince1970: lastSyncAt)
        return date.formatted(date: .abbreviated, time: .shortened)
    }

    /// 모의 데이터 모드와 무관하게 실서버 /health 를 직접 확인
    private func testConnection() async {
        isTestingConnection = true
        defer { isTestingConnection = false }
        do {
            let result = try await LiveAPIClient().health()
            healthMessage = result.status == "ok" ? "정상 ✓" : "응답: \(result.status)"
        } catch {
            healthMessage = "실패: \(error.localizedDescription)"
        }
    }
}
