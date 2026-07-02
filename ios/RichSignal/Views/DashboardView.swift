import SwiftUI

// 대시보드 — 정보 우선순위 (CLAUDE.md):
// ① 신호 변경(액션 필요) → ② 오늘의 거시 국면 → ③ 전체 섹터 현황

struct DashboardView: View {
    @State private var dashboard: DashboardResponse?
    @State private var errorMessage: String?
    @State private var selectedMarket: MarketCode = .KR
    @AppStorage(AppSettings.Key.mockMode) private var mockMode = true

    var body: some View {
        List {
            if let errorMessage, dashboard == nil {
                InlineErrorView(message: errorMessage) { await load() }
                    .listRowSeparator(.hidden)
            }

            if let dashboard {
                signalChangeSection(dashboard)
                regimeSection(dashboard)
                sectorSection(dashboard)
            } else if errorMessage == nil {
                Section {
                    HStack {
                        Spacer()
                        ProgressView("불러오는 중…")
                        Spacer()
                    }
                    .listRowSeparator(.hidden)
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("리치시그널")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if mockMode {
                    Text("모의 데이터")
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.yellow.opacity(0.25), in: Capsule())
                        .accessibilityLabel("모의 데이터 모드")
                }
            }
        }
        .refreshable { await load() }
        .task { await load() }
        .onChange(of: mockMode) { _, _ in
            Task { await load() }
        }
    }

    // MARK: ① 신호 변경

    @ViewBuilder
    private func signalChangeSection(_ data: DashboardResponse) -> some View {
        Section {
            let changed = data.changedSectors
            if changed.isEmpty {
                Label("오늘 변경된 신호 없음", systemImage: "checkmark.circle")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(changed) { snapshot in
                    NavigationLink {
                        SectorDetailView(market: snapshot.market, sector: snapshot.sector)
                    } label: {
                        SignalChangeCard(snapshot: snapshot)
                    }
                }
            }
        } header: {
            Text("신호 변경")
        } footer: {
            Text("기준일 \(data.asOf)")
        }
    }

    // MARK: ② 거시 국면

    @ViewBuilder
    private func regimeSection(_ data: DashboardResponse) -> some View {
        Section("오늘의 거시 국면") {
            HStack(spacing: 10) {
                ForEach(MarketCode.allCases) { market in
                    if let info = data.regime(for: market) {
                        RegimeBadge(market: market, regime: info.regime, localTrend: info.localTrend)
                    }
                }
            }
            .listRowInsets(EdgeInsets(top: 8, leading: 12, bottom: 8, trailing: 12))
        }
    }

    // MARK: ③ 섹터 현황

    @ViewBuilder
    private func sectorSection(_ data: DashboardResponse) -> some View {
        Section("섹터 현황") {
            Picker("시장", selection: $selectedMarket) {
                ForEach(MarketCode.allCases) { market in
                    Text(market.label).tag(market)
                }
            }
            .pickerStyle(.segmented)
            .listRowSeparator(.hidden)

            ForEach(data.sectors(in: selectedMarket)) { snapshot in
                NavigationLink {
                    SectorDetailView(market: snapshot.market, sector: snapshot.sector)
                } label: {
                    SectorCardView(snapshot: snapshot)
                }
            }
        }
    }

    // MARK: 로드

    private func load() async {
        do {
            let client = APIClient.current
            dashboard = try await client.dashboard()
            errorMessage = nil
            AppSettings.lastSyncAt = Date()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

// MARK: - 신호 변경 강조 카드

struct SignalChangeCard: View {
    let snapshot: SectorSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: snapshot.sector.iconName)
                    .foregroundStyle(.secondary)
                Text("\(snapshot.label) · \(snapshot.market.label)")
                    .font(.headline)
                Spacer()
                Text(String(format: "%.0f점", snapshot.score))
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 8) {
                if let prev = snapshot.prevSignal {
                    SignalBadge(signal: prev)
                }
                Image(systemName: "arrow.right")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                SignalBadge(signal: snapshot.signal)
                Spacer()
                ScoreDeltaLabel(delta: snapshot.scoreDelta1D)
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        let prev = snapshot.prevSignal?.label ?? "없음"
        return "\(snapshot.market.label) \(snapshot.label), 신호 변경, \(prev)에서 \(snapshot.signal.label)로"
    }
}

// MARK: - 섹터 카드

struct SectorCardView: View {
    let snapshot: SectorSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                SignalIcon(signal: snapshot.signal)

                VStack(alignment: .leading, spacing: 2) {
                    Text(snapshot.label)
                        .font(.headline)
                    HStack(spacing: 6) {
                        Text(snapshot.signal.label)
                            .font(.caption)
                            .foregroundStyle(snapshot.signal.color)
                        ScoreDeltaLabel(delta: snapshot.scoreDelta1D)
                    }
                }

                Spacer()

                Text(String(format: "%.0f", snapshot.score))
                    .font(.system(.title, design: .rounded).weight(.bold))
                    .monospacedDigit()
                    .foregroundStyle(snapshot.signal.color)
            }

            ComponentBars(snapshot: snapshot)
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(snapshot.label), 신호 \(snapshot.signal.label), 점수 \(Int(snapshot.score.rounded()))점"
        )
    }
}
