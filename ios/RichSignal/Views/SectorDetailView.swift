import SwiftUI
import Charts

// 섹터 상세 — 드릴다운 구조: 요약(신호/국면 방향) → 구성요소(T/V/M) → 원본 데이터(거시 지표/차트/뉴스)

struct SectorDetailView: View {
    let market: MarketCode
    let sector: SectorCode

    @State private var detail: SectorDetailResponse?
    @State private var history: [HistoryPoint] = []
    @State private var errorMessage: String?
    @State private var periodMonths = 6   // 3 또는 6

    var body: some View {
        List {
            if let errorMessage, detail == nil {
                InlineErrorView(message: errorMessage) { await load() }
                    .listRowSeparator(.hidden)
            }

            if let detail {
                summarySection(detail)
                componentSection(detail)
                chartSection
                newsSection(detail)
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
        .navigationTitle("\(sector.label) · \(market.label)")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    // MARK: 요약

    @ViewBuilder
    private func summarySection(_ detail: SectorDetailResponse) -> some View {
        Section {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 12) {
                    SignalIcon(signal: detail.sector.signal)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(detail.sector.signal.label)
                            .font(.title3.weight(.bold))
                            .foregroundStyle(detail.sector.signal.color)
                        Text(detail.sector.stance.label)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(String(format: "%.1f", detail.sector.score))
                            .font(.system(.largeTitle, design: .rounded).weight(.bold))
                            .monospacedDigit()
                        ScoreDeltaLabel(delta: detail.sector.scoreDelta1D)
                    }
                }

                Divider()

                HStack(spacing: 6) {
                    Text("현재 국면에서 이 섹터는")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    BiasDirectionLabel(bias: detail.regimeBias)
                }
            }
            .padding(.vertical, 4)
        }
    }

    // MARK: 구성요소 드릴다운

    @ViewBuilder
    private func componentSection(_ detail: SectorDetailResponse) -> some View {
        Section("구성요소") {
            DisclosureGroup {
                componentRows(value: detail.sector.trend,
                              weight: detail.sector.wTrend)
            } label: {
                componentHeader(label: "추세 (T)", color: .blue,
                                contribution: detail.sector.trendContribution)
            }

            DisclosureGroup {
                componentRows(value: detail.sector.volume,
                              weight: detail.sector.wVolume)
            } label: {
                componentHeader(label: "거래량 (V)", color: .teal,
                                contribution: detail.sector.volumeContribution)
            }

            DisclosureGroup {
                componentRows(value: detail.sector.macro,
                              weight: detail.sector.wMacro)
                macroRawRows(detail.macroRaw)
            } label: {
                componentHeader(label: "거시 (M)", color: .purple,
                                contribution: detail.sector.macroContribution)
            }
        }
    }

    private func componentHeader(label: String, color: Color, contribution: Double) -> some View {
        HStack {
            Circle()
                .fill(color)
                .frame(width: 8, height: 8)
            Text(label)
                .font(.subheadline.weight(.semibold))
            Spacer()
            Text(String(format: "%.1f점 기여", contribution))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func componentRows(value: Double, weight: Double) -> some View {
        detailRow("컴포넌트 값", String(format: "%.2f / 1.00", value))
        detailRow("가중치", String(format: "%.0f%%", weight * 100))
    }

    /// 거시 원본 지표 (nil 항목은 표시 생략)
    @ViewBuilder
    private func macroRawRows(_ raw: MacroRaw) -> some View {
        if let v = raw.yShort {
            detailRow("단기 금리", String(format: "%.2f%%", v))
        }
        if let v = raw.yLong {
            detailRow("장기 금리", String(format: "%.2f%%", v))
        }
        if let v = raw.yLongChg63D {
            detailRow("장기 금리 63일 변화", String(format: "%+.2f%%p", v))
        }
        if let v = raw.vix {
            detailRow("VIX", String(format: "%.1f", v))
        }
        if let v = raw.hySpread {
            detailRow("HY 스프레드", String(format: "%.2f%%p", v))
        }
        if let v = raw.realRate {
            detailRow("실질금리", String(format: "%.2f%%", v))
        }
        if let v = raw.dollarIndex {
            detailRow("달러 인덱스", String(format: "%.1f", v))
        }
        if let v = raw.newsScore {
            HStack {
                Text("뉴스 감성")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                SentimentIcon(sentiment: v)
                Text(String(format: "%+.2f", v))
                    .font(.caption.monospacedDigit())
            }
        }
        if let v = raw.newsZ {
            detailRow("뉴스 감성 z-score", String(format: "%+.2f", v))
        }
    }

    private func detailRow(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.caption.monospacedDigit())
        }
    }

    // MARK: 점수 차트

    private var filteredHistory: [HistoryPoint] {
        Array(history.suffix(periodMonths * 30))
    }

    /// 신호가 전날과 달라진 지점 (전환 마커)
    private var transitionPoints: [HistoryPoint] {
        let items = filteredHistory
        guard items.count > 1 else { return [] }
        return (1..<items.count).compactMap { i in
            items[i].signal != items[i - 1].signal ? items[i] : nil
        }
    }

    @ViewBuilder
    private var chartSection: some View {
        Section("점수 추이") {
            Picker("기간", selection: $periodMonths) {
                Text("3개월").tag(3)
                Text("6개월").tag(6)
            }
            .pickerStyle(.segmented)
            .listRowSeparator(.hidden)

            if filteredHistory.isEmpty {
                Text("히스토리 데이터 없음")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Chart {
                    ForEach(filteredHistory) { point in
                        LineMark(
                            x: .value("날짜", point.dateValue),
                            y: .value("점수", point.score)
                        )
                        .foregroundStyle(Color("AccentColor"))   // 총점 추이 = 브랜드 연두
                        .interpolationMethod(.monotone)
                    }

                    ForEach(transitionPoints) { point in
                        PointMark(
                            x: .value("날짜", point.dateValue),
                            y: .value("점수", point.score)
                        )
                        .foregroundStyle(point.signal.color)
                        .symbol {
                            Image(systemName: point.signal.iconName)
                                .font(.caption2)
                                .foregroundStyle(point.signal.color)
                        }
                    }
                }
                .chartYScale(domain: 0...100)
                .frame(height: 220)
                .padding(.vertical, 4)
                .accessibilityLabel("최근 \(periodMonths)개월 점수 추이 차트, 신호 전환 \(transitionPoints.count)회")

                HStack(spacing: 12) {
                    ForEach([SignalType.hold, .cash, .keep], id: \.rawValue) { signal in
                        HStack(spacing: 3) {
                            Image(systemName: signal.iconName)
                                .font(.caption2)
                                .foregroundStyle(signal.color)
                            Text("\(signal.label) 전환")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    // MARK: 뉴스

    @ViewBuilder
    private func newsSection(_ detail: SectorDetailResponse) -> some View {
        Section("뉴스") {
            if let summary = detail.newsSummary {
                Text(summary)
                    .font(.subheadline)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if detail.newsItems.isEmpty {
                Text("표시할 뉴스 없음")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(detail.newsItems) { item in
                    if let url = URL(string: item.url) {
                        Link(destination: url) {
                            newsRow(item)
                        }
                    } else {
                        newsRow(item)
                    }
                }
            }
        }
    }

    private func newsRow(_ item: NewsItem) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(item.title)
                .font(.subheadline)
                .foregroundStyle(.primary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                SentimentIcon(sentiment: item.sentiment)
                    .font(.caption)
                Text(item.source)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(item.date)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Spacer()
                Image(systemName: "safari")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 2)
    }

    // MARK: 로드

    private func load() async {
        do {
            let client = APIClient.current
            async let detailTask = client.detail(market: market, sector: sector)
            async let historyTask = client.history(market: market, sector: sector, days: 180)
            let (detailResult, historyResult) = try await (detailTask, historyTask)
            detail = detailResult
            history = historyResult.items
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
