import SwiftUI

// 공용 컴포넌트 — 색약 대응 원칙: 색상만으로 의미를 전달하지 않고 항상 아이콘/텍스트 병용

// MARK: - 신호 배지

struct SignalBadge: View {
    let signal: SignalType
    var compact = false

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: signal.iconName)
                .font(compact ? .caption2 : .caption)
            if !compact {
                Text(signal.label)
                    .font(.caption.weight(.semibold))
            }
        }
        .foregroundStyle(signal.color)
        .padding(.horizontal, compact ? 6 : 8)
        .padding(.vertical, 4)
        .background(signal.color.opacity(0.15), in: Capsule())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("신호 \(signal.label)")
    }
}

/// 카드 좌측의 큰 신호 아이콘
struct SignalIcon: View {
    let signal: SignalType

    var body: some View {
        Image(systemName: signal.iconName)
            .font(.title2)
            .foregroundStyle(signal.color)
            .frame(width: 40, height: 40)
            .background(signal.color.opacity(0.15), in: RoundedRectangle(cornerRadius: 10))
            .accessibilityLabel("신호 \(signal.label)")
    }
}

// MARK: - 국면 배지

struct RegimeBadge: View {
    let market: MarketCode
    let regime: RegimeCode
    var localTrend: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                Image(systemName: regime.iconName)
                Text(market.label)
                    .font(.caption.weight(.bold))
            }
            .foregroundStyle(regime.color)

            Text(regime.label)
                .font(.footnote.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)

            if let localTrend {
                Text("로컬 추세: \(LocalTrendDisplay.label(for: localTrend))")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(regime.color.opacity(0.12), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(market.label) 시장, \(regime.label)")
    }
}

// MARK: - 컴포넌트 미니 막대 (T/V/M 기여도)

struct ComponentBars: View {
    let snapshot: SectorSnapshot

    private struct Row: Identifiable {
        let id: String
        let label: String
        let weight: Double
        let value: Double     // 0~1
        let color: Color

        var contribution: Double { weight * value * 100 }
    }

    private var rows: [Row] {
        [
            Row(id: "T", label: "추세", weight: snapshot.wTrend, value: snapshot.trend, color: .blue),
            Row(id: "V", label: "거래량", weight: snapshot.wVolume, value: snapshot.volume, color: .teal),
            Row(id: "M", label: "거시", weight: snapshot.wMacro, value: snapshot.macro, color: .purple),
        ]
    }

    var body: some View {
        let maxWeight = rows.map(\.weight).max() ?? 1
        VStack(spacing: 4) {
            ForEach(rows) { row in
                HStack(spacing: 8) {
                    Text(row.label)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .frame(width: 44, alignment: .leading)

                    // 트랙 길이 = 가중치, 채움 = 컴포넌트 값 → 채움 길이가 w×값 기여도
                    GeometryReader { geo in
                        let trackWidth = geo.size.width * (row.weight / maxWeight)
                        ZStack(alignment: .leading) {
                            Capsule()
                                .fill(Color(.systemFill))
                                .frame(width: trackWidth)
                            Capsule()
                                .fill(row.color)
                                .frame(width: trackWidth * row.value)
                        }
                    }
                    .frame(height: 6)

                    Text(String(format: "%.0f점", row.contribution))
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .frame(width: 36, alignment: .trailing)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(row.label) 기여도 \(Int(row.contribution.rounded()))점")
            }
        }
    }
}

// MARK: - 점수 변화 라벨

struct ScoreDeltaLabel: View {
    let delta: Double?

    var body: some View {
        if let delta {
            HStack(spacing: 2) {
                Image(systemName: iconName(delta))
                Text(String(format: "%+.1f", delta))
                    .monospacedDigit()
            }
            .font(.caption)
            .foregroundStyle(color(delta))
            .accessibilityLabel("어제 대비 \(String(format: "%+.1f", delta))점")
        } else {
            Text("—")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func iconName(_ d: Double) -> String {
        if d > 0.05 { return "arrow.up" }
        if d < -0.05 { return "arrow.down" }
        return "minus"
    }

    private func color(_ d: Double) -> Color {
        if d > 0.05 { return .green }
        if d < -0.05 { return .red }
        return .secondary
    }
}

// MARK: - 국면 bias 방향 (-2 ~ +2)

struct BiasDirectionLabel: View {
    let bias: Int

    private var info: (icon: String, text: String, color: Color) {
        switch bias {
        case 2: ("arrow.up", "강한 강세 방향", .green)
        case 1: ("arrow.up.right", "강세 방향", .green)
        case -1: ("arrow.down.right", "약세 방향", .red)
        case -2: ("arrow.down", "강한 약세 방향", .red)
        default: ("arrow.right", "중립 방향", .secondary)
        }
    }

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: info.icon)
            Text(info.text)
        }
        .font(.subheadline.weight(.semibold))
        .foregroundStyle(info.color)
        .accessibilityLabel("현재 국면에서 \(info.text)")
    }
}

// MARK: - 뉴스 감성 아이콘

struct SentimentIcon: View {
    let sentiment: Double

    private var info: (icon: String, color: Color, label: String) {
        if sentiment > 0.15 { return ("face.smiling", .green, "긍정") }
        if sentiment < -0.15 { return ("cloud.rain", .red, "부정") }
        return ("minus.circle", .secondary, "중립")
    }

    var body: some View {
        Image(systemName: info.icon)
            .foregroundStyle(info.color)
            .accessibilityLabel("감성 \(info.label)")
    }
}

// MARK: - 경제 캘린더

enum CalendarFormat {
    /// "2026-07" → "2026년 7월"
    static func monthTitle(_ month: String) -> String {
        let parts = month.split(separator: "-")
        guard parts.count == 2, let y = Int(parts[0]), let m = Int(parts[1]) else { return month }
        return "\(y)년 \(m)월"
    }

    private static let weekdaySymbols = ["일", "월", "화", "수", "목", "금", "토"]

    /// "2026-07-03" → ("3", "금")
    static func dayAndWeekday(_ date: String) -> (day: String, weekday: String) {
        let d = APIDate.parse(date)
        let cal = Calendar(identifier: .gregorian)
        let day = cal.component(.day, from: d)
        let w = cal.component(.weekday, from: d) - 1   // 1=일 → 0-index
        return ("\(day)", weekdaySymbols[max(0, min(6, w))])
    }

    static func isToday(_ date: String) -> Bool {
        date == APIDate.string(from: Date())
    }
    static func isPast(_ date: String) -> Bool {
        date < APIDate.string(from: Date())
    }
}

/// 캘린더 이벤트 한 줄: [일자] [시장칩] [카테고리아이콘] 제목 [예상]
struct CalendarEventRow: View {
    let event: CalendarEvent

    private var marketColor: Color { event.market == .US ? .blue : .indigo }

    var body: some View {
        HStack(spacing: 10) {
            // 일자
            let dw = CalendarFormat.dayAndWeekday(event.date)
            VStack(spacing: 0) {
                Text(dw.day)
                    .font(.headline.monospacedDigit())
                Text(dw.weekday)
                    .font(.caption2)
                    .foregroundStyle(dw.weekday == "일" ? .red : (dw.weekday == "토" ? .blue : .secondary))
            }
            .frame(width: 34)
            .opacity(CalendarFormat.isPast(event.date) ? 0.45 : 1)

            // 시장 칩
            Text(event.market.label)
                .font(.caption2.weight(.bold))
                .foregroundStyle(marketColor)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(marketColor.opacity(0.15), in: Capsule())

            // 카테고리 아이콘 + 제목
            Image(systemName: event.category.iconName)
                .font(.caption)
                .foregroundStyle(event.category == .earnings ? Color("AccentColor") : .secondary)
            Text(event.title)
                .font(.subheadline)
                .foregroundStyle(CalendarFormat.isPast(event.date) ? .secondary : .primary)
                .lineLimit(1)

            Spacer(minLength: 4)

            // 중요도(높음) 또는 예상 표시
            if !event.confirmed {
                Text("예상")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            } else if event.importance >= 3 {
                Image(systemName: "exclamationmark")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.orange)
            }
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "\(event.market.label) \(CalendarFormat.dayAndWeekday(event.date).day)일, "
            + "\(event.category.label), \(event.title)\(event.confirmed ? "" : ", 예상")"
        )
    }
}

// MARK: - 점수 근거 요약 문구

/// 점수 산출 근거를 줄글로 보여주는 노트 (좌측 연두 강조 바 + 본문).
struct RationaleNote: View {
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            RoundedRectangle(cornerRadius: 1.5)
                .fill(Color("AccentColor"))
                .frame(width: 3)
            Text(text)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("점수 근거. \(text)")
    }
}

// MARK: - 에러/빈 상태

struct InlineErrorView: View {
    let message: String
    let retry: () async -> Void

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "wifi.exclamationmark")
                .font(.largeTitle)
                .foregroundStyle(.secondary)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button("다시 시도") {
                Task { await retry() }
            }
            .buttonStyle(.bordered)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 24)
    }
}
