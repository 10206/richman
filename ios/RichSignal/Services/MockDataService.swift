import Foundation

// 백엔드 없이 전체 화면을 확인할 수 있는 모의 데이터.
// - 시드 고정 의사난수(SplitMix64) → 실행할 때마다 동일한 데이터
// - 12개 섹터 카드 중 2개는 signal_changed=true (US 반도체 보유→현금보유, KR 금 유지→보유)
// - 180일 히스토리는 사인파+노이즈로 생성, 신호 전환 3~4회 포함

// MARK: - 시드 고정 의사난수 (SplitMix64)

struct SeededRandom {
    private var state: UInt64

    init(seed: UInt64) {
        state = seed
    }

    mutating func next() -> UInt64 {
        state = state &+ 0x9E3779B97F4A7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }

    /// [0, 1) 균등분포
    mutating func uniform() -> Double {
        Double(next() >> 11) * (1.0 / 9007199254740992.0)
    }

    /// 대략 [-1, 1] 종형분포
    mutating func noise() -> Double {
        (uniform() + uniform() + uniform()) / 1.5 - 1.0
    }
}

// MARK: - 모의 데이터 서비스

final class MockDataService: SignalDataProviding {
    static let shared = MockDataService()

    private let dayCount = 180
    private var ackedIDs = Set<Int>()

    // MARK: 신호 파라미터 (docs/02 §4 확정값)

    private struct SignalParams {
        let enter: Double
        let exit: Double
        let confirm: Int
    }

    private func params(for sector: SectorCode) -> SignalParams {
        switch sector {
        case .semiconductor, .robotics: SignalParams(enter: 55, exit: 35, confirm: 2)
        case .power, .healthcare: SignalParams(enter: 50, exit: 30, confirm: 3)
        case .gold: SignalParams(enter: 55, exit: 35, confirm: 3)
        case .bonds: SignalParams(enter: 50, exit: 35, confirm: 3)
        }
    }

    private func weights(for sector: SectorCode) -> (t: Double, v: Double, m: Double) {
        switch sector {
        case .bonds: (0.25, 0.10, 0.65)
        case .gold: (0.30, 0.10, 0.60)
        default: (0.45, 0.25, 0.30)   // 주식 섹터 기본 가중치
        }
    }

    /// 국면 → 섹터 반응 방향 bias (docs/01 §4 매트릭스)
    private func bias(sector: SectorCode, regime: RegimeCode) -> Int {
        switch (sector, regime) {
        case (.semiconductor, .G), (.robotics, .G), (.bonds, .G): 2
        case (.semiconductor, .R), (.robotics, .R): 1
        case (.semiconductor, .T), (.robotics, .T): -2
        case (.semiconductor, .F), (.robotics, .F): -1
        case (.power, .G), (.power, .R), (.power, .F): 1
        case (.power, .T): -1
        case (.healthcare, .G), (.healthcare, .F): 1
        case (.healthcare, .R): 0
        case (.healthcare, .T): -1
        case (.gold, .G): 1
        case (.gold, .R): -1
        case (.gold, .T): 0
        case (.gold, .F): 2
        case (.bonds, .R): -2
        case (.bonds, .T): -1
        case (.bonds, .F): 2
        }
    }

    // MARK: 국면 타임라인 (인덱스 0 = 가장 과거)

    private func regime(market: MarketCode, dayIndex: Int) -> RegimeCode {
        switch market {
        case .US:
            if dayIndex < 45 { return .R }
            if dayIndex < 105 { return .T }
            if dayIndex < 140 { return .F }
            return .G
        case .KR:
            if dayIndex < 50 { return .T }
            return .F
        }
    }

    private func currentRegime(_ market: MarketCode) -> RegimeCode {
        regime(market: market, dayIndex: dayCount - 1)
    }

    // MARK: 날짜

    private func dates() -> [Date] {
        let today = Calendar.current.startOfDay(for: Date())
        return (0..<dayCount).map { i in
            Calendar.current.date(byAdding: .day, value: -(dayCount - 1 - i), to: today) ?? today
        }
    }

    // MARK: 컴포넌트 시계열 생성

    private struct DayValues {
        var trend: Double
        var volume: Double
        var macro: Double
        var score: Double
    }

    private func rawSeries(market: MarketCode, sector: SectorCode) -> [DayValues] {
        let si = SectorCode.allCases.firstIndex(of: sector) ?? 0
        let mi = MarketCode.allCases.firstIndex(of: market) ?? 0
        var rng = SeededRandom(seed: UInt64(mi * 1000 + si * 17 + 42))
        let w = weights(for: sector)

        // 주기/위상: 섹터·시장별로 조금씩 다르게 (약 2사이클 → 전환 3~4회)
        let period = Double(80 + (si * 9 + mi * 13) % 28)
        let phase = Double((si * 31 + mi * 47) % 60)

        var series: [DayValues] = []
        series.reserveCapacity(dayCount)
        for d in 0..<dayCount {
            let t = Double(d) + phase
            let base = sin(2.0 * .pi * t / period)
            let trend = clamp01(0.5 + 0.40 * base + 0.06 * rng.noise())
            let volume = clamp01(0.5 + 0.28 * sin(2.0 * .pi * (t + 6) / period) + 0.10 * rng.noise())
            let macro = clamp01(0.5 + 0.32 * sin(2.0 * .pi * (t + 12) / period) + 0.05 * rng.noise())
            let score = 100.0 * (w.t * trend + w.v * volume + w.m * macro)
            series.append(DayValues(trend: trend, volume: volume, macro: macro, score: score))
        }
        return series
    }

    private func clamp01(_ x: Double) -> Double { min(max(x, 0), 1) }

    /// 마지막 이틀 점수를 목표 구간으로 조정 (신호 변경 카드 연출 / 그 외 카드는 변경 억제)
    private func adjustedSeries(market: MarketCode, sector: SectorCode) -> [DayValues] {
        var series = rawSeries(market: market, sector: sector)
        let p = params(for: sector)
        let last = dayCount - 1

        func setScore(_ index: Int, to target: Double) {
            let w = weights(for: sector)
            let original = series[index].score
            let factor = original > 0 ? target / original : 1
            var v = series[index]
            v.trend = clamp01(v.trend * factor)
            v.volume = clamp01(v.volume * factor)
            v.macro = clamp01(v.macro * factor)
            v.score = 100.0 * (w.t * v.trend + w.v * v.volume + w.m * v.macro)
            series[index] = v
        }

        if market == .US && sector == .semiconductor {
            // 보유 → 현금보유 (즉시 알림 시나리오)
            setScore(last - 1, to: p.enter + 8)
            setScore(last, to: p.exit - 3)
        } else if market == .KR && sector == .gold {
            // 유지 → 보유 (다이제스트 시나리오)
            setScore(last - 1, to: (p.enter + p.exit) / 2)
            setScore(last, to: p.enter + 6)
        } else {
            // 나머지 카드는 오늘 신호 변경이 없도록 어제 구간으로 정렬
            let yesterdayZone = zone(series[last - 1].score, p)
            if zone(series[last].score, p) != yesterdayZone {
                setScore(last, to: series[last - 1].score)
            }
        }
        return series
    }

    /// 점수 → 표시 구간 (0=현금, 1=유지, 2=보유)
    private func zone(_ score: Double, _ p: SignalParams) -> Int {
        if score >= p.enter { return 2 }
        if score <= p.exit { return 0 }
        return 1
    }

    private func signal(for score: Double, _ p: SignalParams) -> SignalType {
        switch zone(score, p) {
        case 2: .hold
        case 0: .cash
        default: .keep
        }
    }

    /// 히스테리시스 + 확인일 기반 스탠스 시계열
    private func stances(scores: [Double], _ p: SignalParams) -> [StanceType] {
        var result: [StanceType] = []
        var stance: StanceType = scores.first.map { $0 >= p.enter ? .long : .cash } ?? .cash
        var aboveStreak = 0
        var belowStreak = 0
        for s in scores {
            aboveStreak = s >= p.enter ? aboveStreak + 1 : 0
            belowStreak = s <= p.exit ? belowStreak + 1 : 0
            if stance == .cash && aboveStreak >= p.confirm { stance = .long }
            if stance == .long && belowStreak >= p.confirm { stance = .cash }
            result.append(stance)
        }
        return result
    }

    // MARK: 히스토리 조립

    private func historyPoints(market: MarketCode, sector: SectorCode) -> [HistoryPoint] {
        let series = adjustedSeries(market: market, sector: sector)
        let p = params(for: sector)
        let stanceSeries = stances(scores: series.map(\.score), p)
        let dateList = dates()
        return (0..<dayCount).map { i in
            HistoryPoint(
                date: APIDate.string(from: dateList[i]),
                score: round1(series[i].score),
                trend: round3(series[i].trend),
                volume: round3(series[i].volume),
                macro: round3(series[i].macro),
                signal: signal(for: series[i].score, p),
                stance: stanceSeries[i],
                regime: regime(market: market, dayIndex: i)
            )
        }
    }

    private func round1(_ x: Double) -> Double { (x * 10).rounded() / 10 }
    private func round3(_ x: Double) -> Double { (x * 1000).rounded() / 1000 }

    private func snapshot(market: MarketCode, sector: SectorCode) -> SectorSnapshot {
        let series = adjustedSeries(market: market, sector: sector)
        let p = params(for: sector)
        let w = weights(for: sector)
        let stanceSeries = stances(scores: series.map(\.score), p)
        let last = dayCount - 1
        let today = series[last]
        let yesterday = series[last - 1]
        let currentSignal = signal(for: today.score, p)
        let prevSignal = signal(for: yesterday.score, p)
        return SectorSnapshot(
            market: market,
            sector: sector,
            label: sector.label,
            score: round1(today.score),
            trend: round3(today.trend),
            volume: round3(today.volume),
            macro: round3(today.macro),
            wTrend: w.t,
            wVolume: w.v,
            wMacro: w.m,
            signal: currentSignal,
            stance: stanceSeries[last],
            prevSignal: prevSignal,
            signalChanged: currentSignal != prevSignal,
            scoreDelta1D: round1(today.score - yesterday.score)
        )
    }

    // MARK: - SignalDataProviding

    func health() async throws -> HealthResponse {
        HealthResponse(status: "ok")
    }

    func dashboard() async throws -> DashboardResponse {
        let today = APIDate.string(from: Calendar.current.startOfDay(for: Date()))
        let markets: [String: MarketRegime] = [
            MarketCode.US.rawValue: MarketRegime(
                regime: currentRegime(.US),
                regimeLabel: currentRegime(.US).label,
                rScore: 0.42, lScore: -0.18, localTrend: "bull"
            ),
            MarketCode.KR.rawValue: MarketRegime(
                regime: currentRegime(.KR),
                regimeLabel: currentRegime(.KR).label,
                rScore: -0.35, lScore: -0.22, localTrend: "bear"
            ),
        ]
        var sectors: [SectorSnapshot] = []
        for market in MarketCode.allCases {
            for sector in SectorCode.allCases {
                sectors.append(snapshot(market: market, sector: sector))
            }
        }
        return DashboardResponse(
            asOf: today,
            generatedAt: ISO8601DateFormatter().string(from: Date()),
            markets: markets,
            sectors: sectors
        )
    }

    func history(market: MarketCode, sector: SectorCode, days: Int) async throws -> HistoryResponse {
        let all = historyPoints(market: market, sector: sector)
        return HistoryResponse(items: Array(all.suffix(min(days, dayCount))))
    }

    func detail(market: MarketCode, sector: SectorCode) async throws -> SectorDetailResponse {
        let snap = snapshot(market: market, sector: sector)
        let regimeNow = currentRegime(market)
        let isGold = sector == .gold
        let macroRaw = MacroRaw(
            yShort: market == .US ? 4.12 : 2.86,
            yLong: market == .US ? 4.38 : 3.12,
            yLongChg63D: market == .US ? -0.27 : -0.19,
            vix: 18.4,
            hySpread: 3.41,
            realRate: isGold ? 1.92 : nil,
            dollarIndex: isGold ? 103.6 : nil,
            newsScore: 0.62,   // [0,1], 0.5=중립 — 게이트 통과한 완만한 긍정
            newsZ: 1.35
        )
        return SectorDetailResponse(
            sector: snap,
            regimeBias: bias(sector: sector, regime: regimeNow),
            macroRaw: macroRaw,
            basket: mockBasket(market: market, sector: sector),
            newsSummary: mockNewsSummary(market: market, sector: sector),
            newsItems: mockNewsItems(market: market, sector: sector)
        )
    }

    private func mockBasket(market: MarketCode, sector: SectorCode) -> SectorBasket {
        let krProxy: [SectorCode: (String, String)] = [
            .semiconductor: ("091160", "KODEX 반도체"), .robotics: ("445290", "KODEX K-로봇액티브"),
            .power: ("487240", "KODEX AI전력핵심설비"), .healthcare: ("143860", "TIGER 헬스케어"),
            .gold: ("411060", "ACE KRX금현물"), .bonds: ("148070", "KOSEF 국고채10년"),
        ]
        let usProxy: [SectorCode: (String, String)] = [
            .semiconductor: ("SMH", "VanEck 반도체 (SMH)"), .robotics: ("BOTZ", "Global X 로봇·AI (BOTZ)"),
            .power: ("GRID", "First Trust 스마트그리드 (GRID)"), .healthcare: ("XLV", "Health Care Select (XLV)"),
            .gold: ("GLD", "SPDR 골드 (GLD)"), .bonds: ("TLT", "iShares 미국 20년+ 국채 (TLT)"),
        ]
        let krCons: [SectorCode: [(String, String)]] = [
            .semiconductor: [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("042700", "한미반도체")],
            .robotics: [("454910", "두산로보틱스"), ("277810", "레인보우로보틱스"), ("005930", "삼성전자")],
            .power: [("298040", "효성중공업"), ("267260", "HD현대일렉트릭"), ("010120", "LS ELECTRIC")],
            .healthcare: [("207940", "삼성바이오로직스"), ("068270", "셀트리온"), ("000100", "유한양행")],
        ]
        let usCons: [SectorCode: [(String, String)]] = [
            .semiconductor: [("NVDA", "엔비디아"), ("TSM", "TSMC"), ("AVGO", "브로드컴")],
            .robotics: [("NVDA", "엔비디아"), ("ISRG", "인튜이티브서지컬"), ("ABB", "ABB")],
            .power: [("ETN", "이튼"), ("GEV", "GE버노바"), ("PWR", "콴타서비스")],
            .healthcare: [("LLY", "일라이릴리"), ("UNH", "유나이티드헬스"), ("JNJ", "존슨앤드존슨")],
        ]
        let (pt, pn) = (market == .KR ? krProxy : usProxy)[sector] ?? ("", "")
        let assetType = sector == .gold ? "commodity" : (sector == .bonds ? "bond" : "equity_etf")
        let note: String? = sector == .gold ? "실물 자산(금)을 추종하는 ETF로, 개별 구성종목이 없습니다."
            : (sector == .bonds ? "국채(채권)를 추종하는 ETF로, 개별 구성종목이 없습니다." : nil)
        let cons = (market == .KR ? krCons : usCons)[sector] ?? []
        return SectorBasket(
            market: market,
            proxy: BasketProxy(ticker: pt, name: pn),
            assetType: assetType,
            constituents: cons.map { BasketConstituent(ticker: $0.0, name: $0.1) },
            note: note
        )
    }

    func regimeHistory(market: MarketCode, days: Int) async throws -> RegimeHistoryResponse {
        let dateList = dates()
        let n = min(days, dayCount)
        let items = ((dayCount - n)..<dayCount).map { i in
            RegimePoint(
                date: APIDate.string(from: dateList[i]),
                regime: regime(market: market, dayIndex: i),
                rScore: round3(sin(Double(i) / 30.0) * 0.6),
                lScore: round3(cos(Double(i) / 40.0) * 0.5),
                localTrend: i % 3 == 0 ? "neutral" : (i % 3 == 1 ? "bull" : "bear")
            )
        }
        return RegimeHistoryResponse(items: items)
    }

    func calendar(month: String?) async throws -> CalendarResponse {
        let cal = Calendar(identifier: .gregorian)
        let today = Date()
        let comps = cal.dateComponents([.year, .month], from: today)
        let y = comps.year ?? 2026
        let m = comps.month ?? 7
        let mm = String(format: "%04d-%02d", y, m)
        func d(_ day: Int) -> String { String(format: "%@-%02d", mm, day) }
        let events = [
            CalendarEvent(date: d(1), market: .KR, category: .macro, title: "수출입동향(관세청)", importance: 2, confirmed: false),
            CalendarEvent(date: d(3), market: .US, category: .macro, title: "고용보고서(비농업 고용)", importance: 3, confirmed: false),
            CalendarEvent(date: d(7), market: .KR, category: .macro, title: "소비자물가동향(통계청)", importance: 3, confirmed: false),
            CalendarEvent(date: d(8), market: .US, category: .macro, title: "소비자물가(CPI)", importance: 3, confirmed: false),
            CalendarEvent(date: d(9), market: .KR, category: .macro, title: "한국은행 금통위 정책금리 결정", importance: 3, confirmed: false),
            CalendarEvent(date: d(15), market: .US, category: .earnings, title: "Johnson & Johnson (JNJ) 실적", importance: 2, confirmed: true),
            CalendarEvent(date: d(16), market: .US, category: .earnings, title: "TSMC (TSM) 실적", importance: 2, confirmed: true),
            CalendarEvent(date: d(21), market: .US, category: .macro, title: "소매판매", importance: 2, confirmed: false),
            CalendarEvent(date: d(23), market: .US, category: .earnings, title: "Intel (INTC) 실적", importance: 2, confirmed: true),
            CalendarEvent(date: d(28), market: .US, category: .earnings, title: "Texas Instruments (TXN) 실적", importance: 2, confirmed: true),
            CalendarEvent(date: d(29), market: .US, category: .macro, title: "FOMC 정책금리 결정", importance: 3, confirmed: false),
        ]
        return CalendarResponse(month: mm, events: events)
    }

    func pendingNotifications() async throws -> NotificationsPendingResponse {
        let now = ISO8601DateFormatter().string(from: Date())
        let all = [
            PendingNotification(
                id: 1, createdAt: now, market: .US, sector: .semiconductor,
                eventType: "signal_change",
                title: "반도체(미국) 보유 → 현금보유",
                body: "추세 점수 급락 + 거시 악화로 현금보유 전환",
                immediate: true
            ),
            PendingNotification(
                id: 2, createdAt: now, market: .KR, sector: .gold,
                eventType: "signal_change",
                title: "금(한국) 유지 → 보유",
                body: "실질금리 하락 + 위험회피 수요로 보유 전환",
                immediate: false
            ),
            PendingNotification(
                id: 3, createdAt: now, market: .US, sector: nil,
                eventType: "regime_change",
                title: "미국 거시 국면 변경",
                body: "위험회피(안전자산) 국면 → 이상적 성장 국면",
                immediate: false
            ),
        ]
        return NotificationsPendingResponse(items: all.filter { !ackedIDs.contains($0.id) })
    }

    func ackNotifications(ids: [Int]) async throws -> AckResponse {
        ackedIDs.formUnion(ids)
        return AckResponse(acked: ids.count)
    }

    // MARK: 모의 뉴스

    private func mockNewsSummary(market: MarketCode, sector: SectorCode) -> String? {
        switch sector {
        case .semiconductor:
            "AI 서버 수요는 견조하나 단기 재고 조정 우려가 부각. 주요 파운드리 가동률 전망 하향이 심리에 부담."
        case .robotics:
            "휴머노이드 로봇 상용화 기대가 이어지는 가운데, 주요 업체의 대규모 수주 소식이 투자심리를 지지."
        case .power:
            "데이터센터 전력 수요 급증으로 전력 인프라 투자 확대 기대. 규제 당국의 요금 인상 승인이 실적 가시성 개선."
        case .healthcare:
            "신약 임상 결과 발표가 이어지는 시기. 방어 섹터 특성상 위험회피 국면에서 상대적 강세 유지."
        case .gold:
            "실질금리 하락과 중앙은행 매수세가 금 가격을 지지. 지정학 리스크 헤지 수요도 유입 중."
        case .bonds:
            market == .US
                ? "연준 금리 인하 기대가 강화되며 장기물 중심 강세. 일드커브는 불 스티프닝 진행."
                : "한국은행 완화 기조 지속 전망. 외국인 국채 선물 순매수가 이어지며 금리 하락 압력."
        }
    }

    private func mockNewsItems(market: MarketCode, sector: SectorCode) -> [NewsItem] {
        let dateList = dates()
        let recent = Array(dateList.suffix(3)).map { APIDate.string(from: $0) }
        let marketTag = market.label
        switch sector {
        case .semiconductor:
            return [
                NewsItem(date: recent[2], title: "\(marketTag) 반도체, AI 칩 수요 둔화 우려에 급락",
                         url: "https://example.com/news/semi-1", source: "모의뉴스", sentiment: -0.62),
                NewsItem(date: recent[1], title: "파운드리 가동률 전망 하향… 재고 조정 장기화 가능성",
                         url: "https://example.com/news/semi-2", source: "모의경제", sentiment: -0.41),
                NewsItem(date: recent[0], title: "HBM 신규 수주는 견조, 중장기 성장 스토리 유효",
                         url: "https://example.com/news/semi-3", source: "모의증권", sentiment: 0.35),
            ]
        case .gold:
            return [
                NewsItem(date: recent[2], title: "금값 사상 최고치 근접… 실질금리 하락에 랠리",
                         url: "https://example.com/news/gold-1", source: "모의뉴스", sentiment: 0.71),
                NewsItem(date: recent[1], title: "중앙은행 금 매수 지속, 3분기에도 순매수 확대",
                         url: "https://example.com/news/gold-2", source: "모의경제", sentiment: 0.48),
            ]
        case .bonds:
            return [
                NewsItem(date: recent[2], title: "\(marketTag) 국채 금리 하락… 인하 기대 반영",
                         url: "https://example.com/news/bond-1", source: "모의뉴스", sentiment: 0.52),
                NewsItem(date: recent[0], title: "물가 지표 둔화에 채권시장 강세 지속",
                         url: "https://example.com/news/bond-2", source: "모의경제", sentiment: 0.44),
            ]
        default:
            return [
                NewsItem(date: recent[2], title: "\(marketTag) \(sector.label) 섹터, 수급 개선 흐름",
                         url: "https://example.com/news/\(sector.rawValue)-1", source: "모의뉴스", sentiment: 0.21),
                NewsItem(date: recent[1], title: "\(sector.label) 업종 실적 전망 상향 조정",
                         url: "https://example.com/news/\(sector.rawValue)-2", source: "모의증권", sentiment: 0.33),
                NewsItem(date: recent[0], title: "\(sector.label) 관련 규제 이슈는 중립적 평가",
                         url: "https://example.com/news/\(sector.rawValue)-3", source: "모의경제", sentiment: -0.05),
            ]
        }
    }
}
