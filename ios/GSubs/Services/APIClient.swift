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
    static let insufficientCreditsMessage =
        "Χρειάζεσαι τουλάχιστον 30 συνολικά credits για αυτή τη μεταγραφή."
    static let insufficientPaidCreditsMessage =
        "Χρειάζεσαι τουλάχιστον 30 διαθέσιμα πληρωμένα credits στον λογαριασμό σου για αυτή τη μεταγραφή."
    static let outstandingCreditReversalMessage =
        "Υπάρχει εκκρεμής αντιλογισμός credits στον λογαριασμό σου. Τα πληρωμένα credits δεν μπορούν να χρησιμοποιηθούν μέχρι να τακτοποιηθεί."
    static let transcriptionInProgressMessage =
        "Υπάρχει ήδη μεταγραφή σε εξέλιξη. Περίμενε να ολοκληρωθεί και δοκίμασε ξανά."
    static let idempotencyConflictMessage =
        "Το αποθηκευμένο αίτημα ανήκει σε διαφορετικό ήχο. Επίλεξε ξανά το βίντεο και δοκίμασε εκ νέου."

    let status: Int
    let message: String

    var errorDescription: String? {
        if status == 402 {
            switch message {
            case "Insufficient points":
                return Self.insufficientCreditsMessage
            case "Insufficient paid credits":
                return Self.insufficientPaidCreditsMessage
            case "Outstanding credit reversal":
                return Self.outstandingCreditReversalMessage
            default:
                break
            }
        }
        if status == 409, message == "Transcription is already in progress" {
            return Self.transcriptionInProgressMessage
        }
        if status == 409, message == "Idempotency key conflict" {
            return Self.idempotencyConflictMessage
        }
        return message
    }
}

enum AccountDeletionError: LocalizedError, Sendable {
    case confirmationUnavailable

    var errorDescription: String? {
        "Η τοπική σύνδεση και τα αρχεία διαγράφηκαν. Δεν λάβαμε επιβεβαίωση από το GSubs· αν ο λογαριασμός παραμένει ενεργός, συνδέσου και δοκίμασε ξανά."
    }
}

protocol GSubsAPIClient: Sendable {
    func login(email: String, password: String) async throws -> LoginResult
    func register(email: String, password: String, name: String) async throws
    func profile(token: String) async throws -> UserProfile
    func points(token: String) async throws -> PointsBalance
    func logout(token: String) async
    func deleteAccount(token: String) async throws
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
        let plistValue =
            Bundle.main.object(
                forInfoDictionaryKey: "GSubsAPIBaseURL"
            ) as? String
        #if DEBUG
            return configuredBaseURL(
                debugOverride: ProcessInfo.processInfo.environment["GSUBS_API_BASE_URL"],
                plistValue: plistValue
            )
        #else
            return configuredBaseURL(debugOverride: nil, plistValue: plistValue)
        #endif
    }

    static func configuredBaseURL(
        debugOverride: String?,
        plistValue: String?
    ) -> URL {
        #if DEBUG
            if let debugURL = validatedHTTPBaseURL(debugOverride) {
                return debugURL
            }
        #endif
        return validatedHTTPBaseURL(plistValue)
            ?? URL(string: "https://gsubs.gr")!
    }

    private static func validatedHTTPBaseURL(_ rawValue: String?) -> URL? {
        guard let rawValue else { return nil }
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let components = URLComponents(string: trimmed),
            let scheme = components.scheme?.lowercased(),
            scheme == "http" || scheme == "https",
            components.host?.isEmpty == false
        else {
            return nil
        }
        return components.url
    }

    func login(email: String, password: String) async throws -> LoginResult {
        var request = URLRequest(url: endpoint("/auth/token"))
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        var components = URLComponents()
        components.queryItems = [
            URLQueryItem(name: "username", value: email),
            URLQueryItem(name: "password", value: password),
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
            "name": name,
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

    func deleteAccount(token: String) async throws {
        var request = URLRequest(url: endpoint("/auth/me"))
        request.httpMethod = "DELETE"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        try Task.checkCancellation()

        switch await accountDeletionAttempt(request) {
        case .deleted:
            return
        case .rejected(let error) where error.status == 401 || error.status == 404:
            // An invalid session or missing route/account cannot prove that this
            // request deleted the account. Purge local private state, but report
            // that server confirmation was unavailable.
            throw AccountDeletionError.confirmationUnavailable
        case .rejected(let error):
            throw error
        case .ambiguous:
            break
        }

        guard !Task.isCancelled else {
            throw AccountDeletionError.confirmationUnavailable
        }
        switch await accountDeletionAttempt(request) {
        case .deleted:
            return
        case .rejected(let error) where error.status == 401 || error.status == 404:
            // Neither response distinguishes a committed first DELETE from an
            // invalid session or routing error, so never claim confirmed success.
            throw AccountDeletionError.confirmationUnavailable
        case .rejected(let error):
            throw error
        case .ambiguous:
            throw AccountDeletionError.confirmationUnavailable
        }
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
        let result = try await send(request, as: MobileTranscriptionResult.self)
        guard !result.hasAuthoritativeWalletSnapshot else { return result }

        // A backend-first rollout may briefly return the legacy response that
        // contains only total balance. Refresh before exposing spendable paid
        // credits so the app never treats promotional credits as paid.
        let wallet = try await points(token: token)
        return result.replacingWallet(with: wallet)
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

    private enum AccountDeletionAttempt {
        case deleted
        case rejected(APIError)
        case ambiguous
    }

    private func accountDeletionAttempt(_ request: URLRequest) async -> AccountDeletionAttempt {
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { return .ambiguous }
            guard (200..<300).contains(http.statusCode) else {
                return .rejected(
                    APIError(
                        status: http.statusCode,
                        message: Self.errorMessage(from: data)
                    ))
            }
            // A 2xx status is the deletion commit boundary. The response body is
            // informational and must not keep private local state alive.
            return .deleted
        } catch {
            return .ambiguous
        }
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
            let detail = payload["detail"] as? String
        else {
            return "Το GSubs δεν μπόρεσε να ολοκληρώσει το αίτημα."
        }
        return detail
    }
}

extension APIClient: GSubsAPIClient {}

extension JSONDecoder {
    fileprivate static var gsubs: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}

extension JSONEncoder {
    fileprivate static var gsubs: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
}
