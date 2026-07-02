import Foundation

// MARK: - 데이터 제공 프로토콜 (실서버 / 모의 데이터 공용)

protocol SignalDataProviding {
    func health() async throws -> HealthResponse
    func dashboard() async throws -> DashboardResponse
    func history(market: MarketCode, sector: SectorCode, days: Int) async throws -> HistoryResponse
    func detail(market: MarketCode, sector: SectorCode) async throws -> SectorDetailResponse
    func regimeHistory(market: MarketCode, days: Int) async throws -> RegimeHistoryResponse
    func pendingNotifications() async throws -> NotificationsPendingResponse
    func ackNotifications(ids: [Int]) async throws -> AckResponse
}

// MARK: - 에러

enum APIError: LocalizedError {
    case invalidBaseURL
    case badStatus(Int)
    case emptyBaseURL

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL: "서버 URL 형식이 올바르지 않습니다. 설정을 확인하세요."
        case .badStatus(let code): "서버 오류 (HTTP \(code))"
        case .emptyBaseURL: "서버 URL이 비어 있습니다. 설정에서 입력하거나 모의 데이터 모드를 켜세요."
        }
    }
}

// MARK: - 팩토리

enum APIClient {
    /// 현재 설정 기준 데이터 소스 반환 — mockMode면 MockDataService
    static var current: SignalDataProviding {
        AppSettings.mockMode ? MockDataService.shared : LiveAPIClient()
    }
}

// MARK: - 실서버 클라이언트

struct LiveAPIClient: SignalDataProviding {
    private let session: URLSession

    init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 30
        session = URLSession(configuration: config)
    }

    private var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    private var encoder: JSONEncoder {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }

    private func makeURL(_ path: String, query: [URLQueryItem] = []) throws -> URL {
        let base = AppSettings.baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !base.isEmpty else { throw APIError.emptyBaseURL }
        guard var components = URLComponents(string: base) else { throw APIError.invalidBaseURL }
        components.path = (components.path as NSString).appendingPathComponent(path)
        if !query.isEmpty { components.queryItems = query }
        guard let url = components.url else { throw APIError.invalidBaseURL }
        return url
    }

    private func makeRequest(url: URL, method: String = "GET", body: Data? = nil) -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = method
        let key = AppSettings.apiKey
        if !key.isEmpty {
            request.setValue(key, forHTTPHeaderField: "X-API-Key")
        }
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return request
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        let url = try makeURL(path, query: query)
        let (data, response) = try await session.data(for: makeRequest(url: url))
        try validate(response)
        return try decoder.decode(T.self, from: data)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        let url = try makeURL(path)
        let bodyData = try encoder.encode(body)
        let (data, response) = try await session.data(for: makeRequest(url: url, method: "POST", body: bodyData))
        try validate(response)
        return try decoder.decode(T.self, from: data)
    }

    private func validate(_ response: URLResponse) throws {
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw APIError.badStatus(http.statusCode)
        }
    }

    // MARK: 엔드포인트

    func health() async throws -> HealthResponse {
        try await get("/health")
    }

    func dashboard() async throws -> DashboardResponse {
        try await get("/api/v1/dashboard")
    }

    func history(market: MarketCode, sector: SectorCode, days: Int) async throws -> HistoryResponse {
        try await get("/api/v1/sectors/\(market.rawValue)/\(sector.rawValue)/history",
                      query: [URLQueryItem(name: "days", value: String(days))])
    }

    func detail(market: MarketCode, sector: SectorCode) async throws -> SectorDetailResponse {
        try await get("/api/v1/sectors/\(market.rawValue)/\(sector.rawValue)/detail")
    }

    func regimeHistory(market: MarketCode, days: Int) async throws -> RegimeHistoryResponse {
        try await get("/api/v1/regime/history",
                      query: [URLQueryItem(name: "market", value: market.rawValue),
                              URLQueryItem(name: "days", value: String(days))])
    }

    func pendingNotifications() async throws -> NotificationsPendingResponse {
        try await get("/api/v1/notifications/pending")
    }

    func ackNotifications(ids: [Int]) async throws -> AckResponse {
        try await post("/api/v1/notifications/ack", body: AckRequest(ids: ids))
    }
}
