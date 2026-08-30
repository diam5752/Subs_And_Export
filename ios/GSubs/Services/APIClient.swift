import Foundation

struct LoginResult: Codable, Sendable {
    let accessToken: String
    let tokenType: String
    let userId: String
    let name: String
    let betaCreditsAwarded: Int
}

struct UserProfile: Codable, Sendable {
    let id: String
    let email: String
    let name: String
    let provider: String
}

struct APIError: LocalizedError, Sendable {
    let status: Int
    let message: String
    var errorDescription: String? { message }
}

protocol GSubsAPIClient: Sendable {
    func login(email: String, password: String) async throws -> LoginResult
    func register(email: String, password: String, name: String) async throws
    func profile(token: String) async throws -> UserProfile
    func points(token: String) async throws -> PointsBalance
    func logout(token: String) async
    func transcribe(
        audioURL: URL,
        token: String,
        idempotencyKey: String
    ) async throws -> MobileTranscriptionResult
}

struct APIClient: Sendable {
    let baseURL: URL
    let session: URLSession

    init(baseURL: URL = APIClient.configuredBaseURL(), session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    static func configuredBaseURL() -> URL {
        let rawValue = Bundle.main.object(forInfoDictionaryKey: "GSubsAPIBaseURL") as? String
        return URL(string: rawValue ?? "https://gsubs.gr")!
    }

    func login(email: String, password: String) async throws -> LoginResult {
        var request = URLRequest(url: endpoint("/auth/token"))
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        var components = URLComponents()
        components.queryItems = [
            URLQueryItem(name: "username", value: email),
            URLQueryItem(name: "password", value: password)
        ]
        request.httpBody = components.percentEncodedQuery?.data(using: .utf8)
        return try await send(request, as: LoginResult.self)
    }

    func register(email: String, password: String, name: String) async throws {
        var request = URLRequest(url: endpoint("/auth/register"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder.gsubs.encode([
            "email": email,
            "password": password,
            "name": name
        ])
        let _: UserProfile = try await send(request, as: UserProfile.self)
    }

    func profile(token: String) async throws -> UserProfile {
        try await authenticatedRequest("/auth/me", token: token, as: UserProfile.self)
    }

    func points(token: String) async throws -> PointsBalance {
        try await authenticatedRequest("/auth/points", token: token, as: PointsBalance.self)
    }

    func logout(token: String) async {
        var request = URLRequest(url: endpoint("/auth/logout"))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        _ = try? await session.data(for: request)
    }

    func transcribe(audioURL: URL, token: String, idempotencyKey: String) async throws -> MobileTranscriptionResult {
        try Task.checkCancellation()
        let audio = try Data(contentsOf: audioURL, options: .mappedIfSafe)
        try Task.checkCancellation()
        let request = mobileTranscriptionRequest(
            audio: audio,
            token: token,
            idempotencyKey: idempotencyKey
        )
        return try await send(request, as: MobileTranscriptionResult.self)
    }

    func mobileTranscriptionRequest(
        audio: Data,
        token: String,
        idempotencyKey: String
    ) -> URLRequest {
        var request = URLRequest(url: endpoint("/videos/mobile-transcriptions"))
        request.httpMethod = "POST"
        request.timeoutInterval = 360
        request.httpBody = audio
        request.setValue("audio/mp4", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key")
        request.setValue("30", forHTTPHeaderField: "X-Gsubs-Authorized-Credits")
        return request
    }

    private func authenticatedRequest<T: Decodable>(
        _ path: String,
        token: String,
        as type: T.Type
    ) async throws -> T {
        var request = URLRequest(url: endpoint(path))
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return try await send(request, as: type)
    }

    private func endpoint(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }

    private func send<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        try Task.checkCancellation()
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError(status: 0, message: "Δεν ελήφθη έγκυρη απάντηση από το GSubs.")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError(status: http.statusCode, message: Self.errorMessage(from: data))
        }
        return try JSONDecoder.gsubs.decode(type, from: data)
    }

    private static func errorMessage(from data: Data) -> String {
        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = payload["detail"] as? String else {
            return "Το GSubs δεν μπόρεσε να ολοκληρώσει το αίτημα."
        }
        return detail
    }
}

extension APIClient: GSubsAPIClient {}

private extension JSONDecoder {
    static var gsubs: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}

private extension JSONEncoder {
    static var gsubs: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
}
