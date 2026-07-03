import SwiftUI

// STATE.md "API 계약" 섹션의 응답 모델 (변경 금지 계약).
// JSONDecoder keyDecodingStrategy = .convertFromSnakeCase 전제.
// 주의: 숫자 세그먼트는 "y_long_chg_63d" → yLongChg63D, "score_delta_1d" → scoreDelta1D 로 변환됨.

// MARK: - 열거형

/// 시장 코드
enum MarketCode: String, Codable, CaseIterable, Identifiable {
    case KR
    case US

    var id: String { rawValue }

    var label: String {
        switch self {
        case .KR: "한국"
        case .US: "미국"
        }
    }
}

/// 섹터 코드 (6종)
enum SectorCode: String, Codable, CaseIterable, Identifiable {
    case semiconductor
    case robotics
    case power
    case healthcare
    case gold
    case bonds

    var id: String { rawValue }

    var label: String {
        switch self {
        case .semiconductor: "반도체"
        case .robotics: "로봇"
        case .power: "전력"
        case .healthcare: "헬스케어"
        case .gold: "금"
        case .bonds: "국채"
        }
    }

    /// 카드/상세 화면용 SF Symbol
    var iconName: String {
        switch self {
        case .semiconductor: "cpu"
        case .robotics: "gearshape.2"
        case .power: "bolt.fill"
        case .healthcare: "cross.case"
        case .gold: "circle.hexagongrid.fill"
        case .bonds: "building.columns"
        }
    }
}

/// 매매 신호 3종 — 색약 대응을 위해 색상과 아이콘을 항상 함께 사용
enum SignalType: String, Codable {
    case hold   // 보유
    case cash   // 현금보유
    case keep   // 유지

    var label: String {
        switch self {
        case .hold: "보유"
        case .cash: "현금보유"
        case .keep: "유지"
        }
    }

    var color: Color {
        switch self {
        case .hold: .green
        case .cash: .red
        case .keep: .orange   // 노랑 계열 — 다크모드 가독성 위해 orange 사용
        }
    }

    var iconName: String {
        switch self {
        case .hold: "arrowtriangle.up.fill"
        case .cash: "square.fill"
        case .keep: "play.fill"
        }
    }
}

/// 내부 스탠스 (2상태)
enum StanceType: String, Codable {
    case long = "LONG"
    case cash = "CASH"

    var label: String {
        switch self {
        case .long: "보유 포지션"
        case .cash: "현금 대기"
        }
    }
}

/// 거시 국면 4종 (docs/01 §2)
enum RegimeCode: String, Codable, CaseIterable {
    case G
    case R
    case T
    case F

    var label: String {
        switch self {
        case .G: "이상적 성장 국면"
        case .R: "경기 과열 국면"
        case .T: "긴축 스트레스 국면"
        case .F: "위험회피(안전자산) 국면"
        }
    }

    var detail: String {
        switch self {
        case .G: "위험선호 + 금리 하락. 성장주에 가장 유리한 조합."
        case .R: "위험선호 + 금리 상승. 경기 재팽창, 실물·가치주 우위."
        case .T: "위험회피 + 금리 상승. 긴축 충격, 대부분 자산에 역풍."
        case .F: "위험회피 + 금리 하락. 안전자산(국채·금) 도피 수요."
        }
    }

    var color: Color {
        switch self {
        case .G: .green
        case .R: .orange
        case .T: .red
        case .F: .indigo
        }
    }

    var iconName: String {
        switch self {
        case .G: "sun.max.fill"
        case .R: "flame.fill"
        case .T: "exclamationmark.triangle.fill"
        case .F: "shield.fill"
        }
    }
}

// MARK: - 대시보드

struct DashboardResponse: Codable {
    let asOf: String
    let generatedAt: String
    let markets: [String: MarketRegime]   // 키: "US" / "KR"
    let sectors: [SectorSnapshot]

    func regime(for market: MarketCode) -> MarketRegime? {
        markets[market.rawValue]
    }

    func sectors(in market: MarketCode) -> [SectorSnapshot] {
        sectors.filter { $0.market == market }
    }

    var changedSectors: [SectorSnapshot] {
        sectors.filter(\.signalChanged)
    }
}

struct MarketRegime: Codable {
    let regime: RegimeCode
    let regimeLabel: String
    let rScore: Double
    let lScore: Double
    let localTrend: String   // 로컬 추세 하위상태 (표기는 LocalTrendDisplay 참고)
}

/// local_trend 원본 문자열을 한국어 표기로 변환 (백엔드 표기 미확정 → 영/한 모두 수용)
enum LocalTrendDisplay {
    static func label(for raw: String) -> String {
        switch raw.lowercased() {
        case "bull", "bullish", "up", "strong", "강세": return "강세"
        case "bear", "bearish", "down", "weak", "약세": return "약세"
        case "neutral", "flat", "중립": return "중립"
        default: return raw
        }
    }
}

struct SectorSnapshot: Codable, Identifiable {
    let market: MarketCode
    let sector: SectorCode
    let label: String
    let score: Double            // 0~100
    let trend: Double            // T 컴포넌트 0~1
    let volume: Double           // V 컴포넌트 0~1
    let macro: Double            // M 컴포넌트 0~1
    let wTrend: Double
    let wVolume: Double
    let wMacro: Double
    let signal: SignalType
    let stance: StanceType
    let prevSignal: SignalType?
    let signalChanged: Bool
    let scoreDelta1D: Double?    // 원본 키 score_delta_1d

    var id: String { "\(market.rawValue)-\(sector.rawValue)" }

    /// 가중 기여도 (점수 단위, 0~100 스케일)
    var trendContribution: Double { wTrend * trend * 100 }
    var volumeContribution: Double { wVolume * volume * 100 }
    var macroContribution: Double { wMacro * macro * 100 }
}

// MARK: - 히스토리

struct HistoryResponse: Codable {
    let items: [HistoryPoint]
}

struct HistoryPoint: Codable, Identifiable {
    let date: String             // "YYYY-MM-DD"
    let score: Double
    let trend: Double
    let volume: Double
    let macro: Double
    let signal: SignalType
    let stance: StanceType
    let regime: RegimeCode

    var id: String { date }
    var dateValue: Date { APIDate.parse(date) }
}

// MARK: - 섹터 상세

struct SectorDetailResponse: Codable {
    let sector: SectorSnapshot
    let regimeBias: Int          // -2 ~ +2
    let macroRaw: MacroRaw
    let basket: SectorBasket?    // 섹터 구성 (프록시 ETF + 대표 구성종목)
    let newsSummary: String?
    let newsItems: [NewsItem]
}

struct SectorBasket: Codable {
    let market: MarketCode
    let proxy: BasketProxy
    let assetType: String        // equity_etf | commodity | bond
    let constituents: [BasketConstituent]
    let note: String?
}

struct BasketProxy: Codable {
    let ticker: String
    let name: String
}

struct BasketConstituent: Codable, Identifiable {
    let ticker: String
    let name: String
    var id: String { ticker.isEmpty ? name : ticker }
    /// "삼성전자 (005930)" — ticker 없으면 이름만
    var display: String { ticker.isEmpty ? name : "\(name) (\(ticker))" }
}

struct MacroRaw: Codable {
    let yShort: Double?          // 단기 금리 (%)
    let yLong: Double?           // 장기 금리 (%)
    let yLongChg63D: Double?     // 장기 금리 63일 변화 (%p) — 원본 키 y_long_chg_63d
    let vix: Double?
    let hySpread: Double?        // HY 신용스프레드 (%p)
    let realRate: Double?        // 실질금리 (금 섹터)
    let dollarIndex: Double?     // 달러 인덱스 (금 섹터)
    let newsScore: Double?       // 뉴스 감성 점수
    let newsZ: Double?           // 뉴스 감성 z-score
}

struct NewsItem: Codable, Identifiable {
    let date: String
    let title: String
    let url: String
    let source: String
    let sentiment: Double        // 음수=부정, 0 근처=중립, 양수=긍정 (가정: AGENT_NOTES 참고)

    var id: String { url + date }
}

// MARK: - 경제 캘린더

struct CalendarResponse: Codable {
    let month: String            // "YYYY-MM"
    let events: [CalendarEvent]

    /// 오늘 이후(다가오는) 일정을 먼저, 지난 일정을 뒤로 — 각 구간은 날짜 오름차순.
    var upcomingThenPast: [CalendarEvent] {
        let today = APIDate.string(from: Date())
        let sorted = events.sorted { $0.date < $1.date }
        let upcoming = sorted.filter { $0.date >= today }
        let past = sorted.filter { $0.date < today }
        return upcoming + past
    }
}

struct CalendarEvent: Codable, Identifiable {
    let date: String             // "YYYY-MM-DD"
    let market: MarketCode
    let category: CalendarCategory
    let title: String
    let importance: Int          // 1~3 (3=최상)
    let confirmed: Bool          // true=확정(실적), false=예상(거시 정례주기)

    var id: String { "\(date)-\(market.rawValue)-\(title)" }
    var dateValue: Date { APIDate.parse(date) }
}

enum CalendarCategory: String, Codable {
    case earnings   // 실적
    case macro      // 거시 지표

    var label: String { self == .earnings ? "실적" : "지표" }
    var iconName: String { self == .earnings ? "building.2.fill" : "chart.xyaxis.line" }
}

// MARK: - 국면 히스토리

struct RegimeHistoryResponse: Codable {
    let items: [RegimePoint]
}

struct RegimePoint: Codable, Identifiable {
    let date: String
    let regime: RegimeCode
    let rScore: Double
    let lScore: Double
    let localTrend: String

    var id: String { date }
}

// MARK: - 알림

struct NotificationsPendingResponse: Codable {
    let items: [PendingNotification]
}

struct PendingNotification: Codable, Identifiable {
    let id: Int
    let createdAt: String
    let market: MarketCode
    let sector: SectorCode?      // 국면 변경 이벤트는 특정 섹터 없음
    let eventType: String
    let title: String
    let body: String
    let immediate: Bool
}

struct AckRequest: Codable {
    let ids: [Int]
}

struct AckResponse: Codable {
    let acked: Int
}

// MARK: - 헬스체크

struct HealthResponse: Codable {
    let status: String
}

// MARK: - 날짜 유틸

enum APIDate {
    /// "YYYY-MM-DD" 파서 (UTC 아닌 로컬 자정 — 차트 축 표기용)
    static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    static func parse(_ s: String) -> Date {
        dayFormatter.date(from: s) ?? .distantPast
    }

    static func string(from date: Date) -> String {
        dayFormatter.string(from: date)
    }

    /// ISO8601 (generated_at 등) 파서
    static func parseISO(_ s: String) -> Date? {
        let iso = ISO8601DateFormatter()
        if let d = iso.date(from: s) { return d }
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return iso.date(from: s)
    }
}
