import Foundation

// 점수 산출 근거를 규칙 기반으로 요약 (인앱 LLM 없음 — docs/02 스코어링 로직을 자연어로 풀어씀).
// 앱이 이미 받은 값/가중치/거시 원본지표만으로 생성하므로 백엔드 호출·모의 모드 모두에서 동작한다.

enum ScoreExplainer {

    // 0~1 컴포넌트 값의 강도 표현
    private static func strength(_ v: Double) -> String {
        switch v {
        case 0.65...: return "뚜렷한 우위"
        case 0.55..<0.65: return "완만한 우위"
        case 0.45..<0.55: return "중립"
        case 0.35..<0.45: return "완만한 열위"
        default: return "뚜렷한 열위"
        }
    }

    private static func wpct(_ w: Double) -> String { String(format: "%.0f%%", w * 100) }
    private static func pt(_ v: Double) -> String { String(format: "%.0f", v) }
    private static func val(_ v: Double) -> String { String(format: "%.2f", v) }

    // MARK: - 종합 요약 (상단 그룹)

    static func overall(_ detail: SectorDetailResponse) -> String {
        let s = detail.sector
        let parts: [(name: String, c: Double)] = [
            ("추세", s.trendContribution),
            ("거래량", s.volumeContribution),
            ("거시", s.macroContribution),
        ]
        let lead = parts.max { $0.c < $1.c }!

        let biasPhrase: String
        switch detail.regimeBias {
        case 2: biasPhrase = "현재 거시 국면에서 강한 강세 방향으로 분류돼 거시 요소가 점수를 끌어올립니다"
        case 1: biasPhrase = "현재 거시 국면에서 강세 방향으로 분류됩니다"
        case -1: biasPhrase = "현재 거시 국면에서 약세 방향으로 분류돼 거시 요소가 점수를 눌러 내립니다"
        case -2: biasPhrase = "현재 거시 국면에서 강한 약세 방향으로 분류돼 거시 요소가 점수를 크게 눌러 내립니다"
        default: biasPhrase = "현재 거시 국면에서 중립(방향성 미확정)입니다"
        }

        let signalPhrase: String
        switch s.signal {
        case .hold: signalPhrase = "점수가 진입 기준선을 웃돌아 ‘보유’ 신호입니다"
        case .cash: signalPhrase = "점수가 이탈 기준선을 밑돌아 ‘현금보유’ 신호입니다"
        case .keep: signalPhrase = "점수가 진입·이탈 기준선 사이(중간 구간)에 있어 직전 신호를 ‘유지’합니다"
        }

        var text = "종합 \(String(format: "%.1f", s.score))점은 추세 \(pt(s.trendContribution))·거래량 "
            + "\(pt(s.volumeContribution))·거시 \(pt(s.macroContribution))점 기여의 합이며, "
            + "\(lead.name) 요소의 비중이 가장 큽니다. 이 섹터는 \(biasPhrase). \(signalPhrase)."

        if let d = s.scoreDelta1D, abs(d) >= 0.1 {
            let dir = d > 0 ? "올랐" : "내렸"
            // 델타 방향이 현재 신호와 같은 방향인지에 따라 어미를 다르게
            let aligns = (s.signal == .hold && d > 0) || (s.signal == .cash && d < 0)
            let tail: String
            if s.signal == .keep {
                tail = "지만 신호를 바꿀 정도는 아닙니다"
            } else if aligns {
                tail = "고 그 흐름이 현재 신호를 뒷받침합니다"
            } else {
                tail = "지만 아직 신호를 바꿀 만큼은 아닙니다"
            }
            text += " 어제보다 \(String(format: "%+.1f", d))점 \(dir)\(tail)."
        }
        return text
    }

    // MARK: - 컴포넌트별 요약 (구성요소 그룹 확장 시)

    static func trend(_ detail: SectorDetailResponse) -> String {
        let v = detail.sector.trend
        let core: String
        switch v {
        case 0.6...: core = "가격이 중기 이동평균을 웃돌고 단기·중기선이 정배열이라 상승 추세가 우위입니다."
        case 0.4..<0.6: core = "가격과 이동평균이 얽혀 있어 방향성이 뚜렷하지 않은 중립 구간입니다."
        default: core = "가격이 중기 이동평균을 밑돌고 역배열이라 하락 추세가 우위입니다."
        }
        return "추세 값 \(val(v)) — \(strength(v)). 이동평균 대비 위치, 단기·중기선 정배열, 3개월 모멘텀을 합성한 값으로 클수록 상승 추세가 강합니다. \(core) 가중치 \(wpct(detail.sector.wTrend))."
    }

    static func volume(_ detail: SectorDetailResponse) -> String {
        let v = detail.sector.volume
        let core: String
        switch v {
        case 0.6...: core = "최근 상승일에 거래량이 더 실려 매집(매수 우위) 신호입니다."
        case 0.4..<0.6: core = "상승·하락 어느 쪽에도 거래량이 뚜렷이 쏠리지 않은 상태입니다."
        default: core = "하락일에 거래량이 더 실려 분산(매도 우위) 신호입니다."
        }
        return "거래량 값 \(val(v)) — \(strength(v)). 거래량의 크기 자체가 아니라 ‘어느 방향에 실렸는지’(상승일 대비 거래량 비중·OBV)를 봅니다. \(core) 가중치 \(wpct(detail.sector.wVolume))."
    }

    static func macro(_ detail: SectorDetailResponse) -> String {
        let s = detail.sector
        let raw = detail.macroRaw
        let w = wpct(s.wMacro)
        let v = val(s.macro)
        let str = strength(s.macro)

        switch s.sector {
        case .bonds:
            var t = "거시 값 \(v) — \(str). 국채 거시 점수는 금리 방향(45%)·장단기 커브(25%)·위험회피 심리(30%)로 구성되며, 사실상 금리가 점수를 좌우합니다. "
            t += rateClause(raw.yLongChg63D, asset: "채권 가격")
            t += " 가중치 \(w)."
            return t

        case .gold:
            var t = "거시 값 \(v) — \(str). 금 거시 점수는 실질금리(40%)·달러 인덱스(30%)·위험회피 심리(30%)로 구성됩니다. "
            if let rr = raw.realRate {
                t += "실질금리 \(String(format: "%.2f", rr))%는 금 보유의 기회비용으로, 낮을수록 금에 우호적입니다. "
            }
            if let dx = raw.dollarIndex {
                t += "달러 인덱스 \(String(format: "%.1f", dx))와는 역상관입니다. "
            }
            t += "가중치 \(w)."
            return t

        default:
            // 주식 섹터 (반도체·로봇·전력·헬스케어)
            var t = "거시 값 \(v) — \(str). 이 섹터의 거시 점수는 현재 국면에서의 방향성에 시장 추세·금리 민감도·뉴스 감성을 더해 산출합니다. "
            switch detail.regimeBias {
            case 2, 1: t += "지금은 강세 방향이라 거시가 점수를 받쳐 줍니다. "
            case -1, -2: t += "지금은 약세 방향이라 거시가 점수를 눌러 내립니다. "
            default: t += "지금은 방향성이 중립이라 거시 기여가 크지 않습니다. "
            }
            let growth = (s.sector == .semiconductor || s.sector == .robotics)
            if let chg = raw.yLongChg63D {
                if chg > 0.5 {
                    t += growth
                        ? "장기 금리가 63일간 +\(String(format: "%.2f", chg))%p 급등해 고금리 민감 성장주에 페널티가 적용됩니다. "
                        : "장기 금리가 +\(String(format: "%.2f", chg))%p 올랐지만 방어 섹터라 영향은 절반 수준입니다. "
                } else if chg < -0.5 {
                    t += "장기 금리가 63일간 \(String(format: "%.2f", chg))%p 급락해 이 섹터에 우호적입니다. "
                } else {
                    t += "장기 금리 변화(\(String(format: "%+.2f", chg))%p)는 불감대 안이라 점수에 영향이 없습니다. "
                }
            }
            if let ns = raw.newsScore {
                if abs(ns - 0.5) < 0.001 {
                    t += "뉴스 감성은 유의 신호 기준(폭·강도·지속)에 못 미쳐 중립 처리됩니다. "
                } else {
                    t += "뉴스 감성이 필터를 통과해 \(ns > 0.5 ? "긍정" : "부정") 방향으로 소폭 반영됩니다. "
                }
            }
            t += "가중치 \(w)."
            return t
        }
    }

    private static func rateClause(_ chg: Double?, asset: String) -> String {
        guard let chg else { return "최근 금리 변화 데이터가 없습니다." }
        if chg < -0.1 {
            return "장기 금리가 63일간 \(String(format: "%.2f", chg))%p 하락해 \(asset)에 순풍입니다."
        } else if chg > 0.1 {
            return "장기 금리가 63일간 +\(String(format: "%.2f", chg))%p 상승해 \(asset)에 역풍입니다."
        } else {
            return "장기 금리 변화가 \(String(format: "%+.2f", chg))%p로 미미해 방향성이 약합니다."
        }
    }
}
