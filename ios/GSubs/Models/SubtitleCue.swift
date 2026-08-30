import Foundation

struct SubtitleWord: Codable, Equatable, Sendable {
    let start: Double
    let end: Double
    let text: String
}

struct SubtitleCue: Codable, Equatable, Identifiable, Sendable {
    let start: Double
    let end: Double
    var text: String
    let words: [SubtitleWord]

    var id: String { "\(start)-\(end)" }

    func contains(_ time: Double) -> Bool {
        time >= start && time < end
    }
}

struct MobileTranscriptionResult: Codable, Equatable, Sendable {
    let requestId: String
    let durationSeconds: Double
    let creditsCharged: Int
    let balance: Int
    let videoUploaded: Bool
    let serverMediaRetained: Bool
    let cues: [SubtitleCue]
}

struct PointsBalance: Codable, Equatable, Sendable {
    let balance: Int
    let paidBalance: Int
    let promotionalBalance: Int
    let reversalDebt: Int
    let aiSpendableBalance: Int
}

struct SubtitleStyle: Equatable, Sendable {
    var fontScale = 1.0
    var bottomOffset = 0.12
    var foreground = SubtitleColor.yellow
}

enum SubtitleColor: String, CaseIterable, Identifiable, Sendable {
    case yellow
    case white
    case cyan

    var id: String { rawValue }
}
