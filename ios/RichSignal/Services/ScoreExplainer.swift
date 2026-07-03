import Foundation

// 점수 근거 요약 — "값이 무엇인지"가 아니라 "최근 값이 왜 변했는지 + 투자 관점 해석"을 규칙 기반으로 생성.
// 앱이 이미 로드한 히스토리(구성요소 시계열)로 최근 변화를 계산 → 인앱 LLM 없음, 즉시·무료, 모의 모드도 동작.

enum ScoreExplainer {
    private static let lookback = 10   // 최근 변화 관찰 창 (거래일)

    struct Delta { let old: Double; let now: Double; let days: Int
        var change: Double { now - old } }

    /// 히스토리에서 특정 컴포넌트의 (과거값→현재값, 실제 거래일수) 추출.
    private static func delta(_ history: [HistoryPoint], _ key: (HistoryPoint) -> Double) -> Delta? {
        guard let last = history.last, history.count >= 2 else { return nil }
        let backIdx = max(0, history.count - 1 - lookback)
        let days = (history.count - 1) - backIdx
        guard days >= 1 else { return nil }
        return Delta(old: key(history[backIdx]), now: key(last), days: days)
    }

    private static func f1(_ v: Double) -> String { String(format: "%.1f", v) }
    private static func f2(_ v: Double) -> String { String(format: "%.2f", v) }
    private static func s1(_ v: Double) -> String { String(format: "%+.1f", v) }
    private static func s2(_ v: Double) -> String { String(format: "%+.2f", v) }

    private static func trendWord(_ c: Double, eps: Double = 0.02) -> String {
        c > eps ? "개선" : (c < -eps ? "악화" : "정체")
    }

    // MARK: - 종합 (상단): 무엇이 점수 변화를 주도했고, 투자 관점에서 어떤 국면인지

    static func overall(_ detail: SectorDetailResponse, history: [HistoryPoint]) -> String {
        let s = detail.sector
        let dS = delta(history) { $0.score }
        let dT = delta(history) { $0.trend }
        let dV = delta(history) { $0.volume }
        let dM = delta(history) { $0.macro }

        // 각 컴포넌트가 점수 변화에 기여한 정도 ≈ 현재 가중치 × 값 변화 × 100
        let cT = s.wTrend * (dT?.change ?? 0) * 100
        let cV = s.wVolume * (dV?.change ?? 0) * 100
        let cM = s.wMacro * (dM?.change ?? 0) * 100
        let parts = [("추세", cT), ("거래량", cV), ("거시", cM)]
        let lead = parts.max { abs($0.1) < abs($1.1) }

        var text: String
        if let dS, abs(dS.change) >= 0.1, let lead, abs(lead.1) >= 0.1 {
            let dir = dS.change > 0 ? "상승" : "하락"
            let leadDir = lead.1 > 0 ? "끌어올렸" : "끌어내렸"
            text = "최근 \(dS.days)거래일 종합 \(f1(dS.old))→\(f1(dS.now))점(\(s1(dS.change))). "
                + "\(lead.0) 요인이 점수를 가장 크게 \(leadDir)습니다(\(s1(lead.1))점 기여). 이번 \(dir)의 핵심 동인입니다. "
        } else if let dS, abs(dS.change) < 0.1 {
            text = "최근 \(dS.days)거래일 종합 점수는 \(f1(dS.now))점으로 큰 변화 없이 횡보 중입니다. "
        } else {
            text = "종합 \(f1(s.score))점. "
        }

        // 투자 관점 프레이밍
        switch s.signal {
        case .hold:
            text += "국면상 \(biasWord(detail.regimeBias)) 방향이고 점수가 진입선 위에 있어, 보유·추세추종에 우호적인 구간입니다."
        case .cash:
            text += "점수가 이탈선 아래로 내려 방어(현금 비중 확대)가 우선인 구간입니다."
        case .keep:
            text += "점수가 진입·이탈선 사이라 신규 진입보다 관망이 적절합니다."
        }

        // 리스크 단서: 추세는 개선인데 거래량이 못 따라오면 지속성 경고
        if let dT, let dV, dT.change > 0.02, dV.change <= 0 {
            text += " 다만 상승에 거래량이 실리지 않아 추세 지속력은 확인이 필요합니다."
        } else if let dM, dM.change < -0.03, s.signal == .hold {
            text += " 거시 여건이 약해지고 있어 하방 리스크를 함께 볼 필요가 있습니다."
        }
        return text
    }

    // MARK: - 추세 (T)

    static func trend(_ detail: SectorDetailResponse, history: [HistoryPoint]) -> String {
        let v = detail.sector.trend
        guard let d = delta(history, { $0.trend }) else {
            return levelOnlyTrend(v)
        }
        let word = trendWord(d.change)
        var t = "추세 \(f2(d.old))→\(f2(d.now)) (최근 \(d.days)거래일, \(s2(d.change)), \(word)). "
        if d.change > 0.02 {
            t += v >= 0.6
                ? "가격이 이동평균을 상향 돌파하고 단기선이 정배열로 돌아서며 상승 모멘텀이 붙었습니다. 추세추종 매수에 우호적입니다."
                : "낙폭이 줄며 하락 압력이 완화되는 초기 신호입니다. 다만 아직 추세 전환을 단정하긴 이릅니다."
        } else if d.change < -0.02 {
            t += v <= 0.4
                ? "가격이 이동평균을 이탈하고 모멘텀이 꺾이며 하락 추세가 강화됐습니다. 추격 매수보다 리스크 관리가 우선입니다."
                : "상승 탄력이 둔화되는 구간입니다. 추세가 유지되는지 확인이 필요합니다."
        } else {
            t += "방향성이 뚜렷하지 않은 횡보 구간으로, 추세 신호의 신뢰도가 낮습니다."
        }
        return t
    }

    // MARK: - 거래량 (V)

    static func volume(_ detail: SectorDetailResponse, history: [HistoryPoint]) -> String {
        let v = detail.sector.volume
        guard let d = delta(history, { $0.volume }) else {
            return levelOnlyVolume(v)
        }
        let word = trendWord(d.change)
        var t = "거래량 \(f2(d.old))→\(f2(d.now)) (최근 \(d.days)거래일, \(s2(d.change)), \(word)). "
        if d.change > 0.02 {
            t += "상승일에 거래량이 실리며 매집(매수 우위)이 강해졌습니다. 추세를 확증하는 수급으로 신뢰도를 높입니다."
        } else if d.change < -0.02 {
            t += v < 0.5
                ? "하락일에 거래량이 실리며 분산(매도 우위)이 진행 중입니다. 수급이 이탈하는 경계 신호입니다."
                : "상승에 실리던 거래량이 줄며 매수 강도가 약해졌습니다. 추세 지속력에 대한 확인이 필요합니다."
        } else {
            t += "수급 방향이 뚜렷하지 않아, 가격 추세를 확증하거나 되돌릴 힘이 아직 약합니다."
        }
        return t
    }

    // MARK: - 거시 (M): 왜 변했나 = 금리·국면·달러 등 동인 + 투자 시사점

    static func macro(_ detail: SectorDetailResponse, history: [HistoryPoint]) -> String {
        let s = detail.sector
        let raw = detail.macroRaw
        let d = delta(history, { $0.macro })
        let head: String
        if let d {
            head = "거시 \(f2(d.old))→\(f2(d.now)) (최근 \(d.days)거래일, \(s2(d.change)), \(trendWord(d.change))). "
        } else {
            head = "거시 \(f2(s.macro)). "
        }

        switch s.sector {
        case .bonds:
            var t = head
            if let chg = raw.yLongChg63D {
                if chg > 0.1 { t += "장기 금리가 63일간 +\(f2(chg))%p 올라 채권 가격에 하락 압력이 이어졌습니다. 금리 고점 신호가 확인되기 전엔 방어적 접근이 유효합니다." }
                else if chg < -0.1 { t += "장기 금리가 63일간 \(f2(chg))%p 내리며 채권 가격이 지지받았습니다. 금리 하락(인하 기대) 추세가 국채에 우호적입니다." }
                else { t += "금리 방향성이 약해 국채는 뚜렷한 추세 없이 등락하는 구간입니다." }
            }
            return t
        case .gold:
            var t = head + "금은 실질금리와 달러의 움직임에 좌우됩니다. "
            if let rr = raw.realRate { t += "현재 실질금리 \(f2(rr))%로, 낮을수록(보유 기회비용↓) 금에 우호적입니다. " }
            if let dx = raw.dollarIndex { t += "달러 인덱스 \(String(format: "%.1f", dx))의 강세는 금엔 역풍입니다. " }
            t += (d?.change ?? 0) >= 0 ? "실질금리·달러 여건이 금에 우호적으로 기울고 있습니다." : "실질금리·달러 부담이 커지는 구간입니다."
            return t
        default:
            // 주식 섹터
            var t = head
            t += biasWord(detail.regimeBias) == "강세"
                ? "현재 국면이 이 섹터에 강세로 작용해 거시가 점수를 받칩니다. "
                : (biasWord(detail.regimeBias) == "약세"
                   ? "현재 국면이 약세 방향이라 거시가 하방 압력으로 작용합니다. "
                   : "국면 방향이 중립이라 거시 기여가 크지 않습니다. ")
            let growth = (s.sector == .semiconductor || s.sector == .robotics)
            if let chg = raw.yLongChg63D {
                if chg > 0.5 { t += growth ? "장기 금리 급등(+\(f2(chg))%p)이 고밸류 성장주에 부담을 더했습니다. " : "금리 상승(+\(f2(chg))%p)은 방어 섹터라 영향이 제한적입니다. " }
                else if chg < -0.5 { t += "장기 금리 급락(\(f2(chg))%p)이 밸류에이션에 우호적으로 작용했습니다. " }
            }
            t += (d?.change ?? 0) >= 0 ? "거시가 개선되며 신호를 뒷받침하는 방향입니다." : "거시가 약해지며 하방 리스크 요인으로 작용합니다."
            return t
        }
    }

    // MARK: - 보조

    private static func biasWord(_ bias: Int) -> String {
        if bias >= 1 { return "강세" }
        if bias <= -1 { return "약세" }
        return "중립"
    }

    // 히스토리가 없을 때(값만): 최소한의 변화 없는 서술
    private static func levelOnlyTrend(_ v: Double) -> String {
        v >= 0.6 ? "추세 \(f2(v)) — 상승 우위. 추세추종 매수에 우호적인 구간입니다."
            : (v <= 0.4 ? "추세 \(f2(v)) — 하락 우위. 리스크 관리가 우선입니다." : "추세 \(f2(v)) — 중립. 방향성이 뚜렷하지 않습니다.")
    }
    private static func levelOnlyVolume(_ v: Double) -> String {
        v >= 0.6 ? "거래량 \(f2(v)) — 매수 우위(매집). 추세를 확증하는 수급입니다."
            : (v <= 0.4 ? "거래량 \(f2(v)) — 매도 우위(분산). 수급 이탈 경계 신호입니다." : "거래량 \(f2(v)) — 중립. 수급 방향이 뚜렷하지 않습니다.")
    }
}
