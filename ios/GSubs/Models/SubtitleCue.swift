import Foundation
import UIKit

struct SubtitleWord: Codable, Equatable, Sendable {
    let start: Double
    let end: Double
    let text: String
}

struct SubtitleCue: Codable, Equatable, Identifiable, Sendable {
    let id: UUID
    let start: Double
    let end: Double
    var text: String
    let words: [SubtitleWord]
    var bottomOffsetOverride: Double?

    init(
        id: UUID = UUID(),
        start: Double,
        end: Double,
        text: String,
        words: [SubtitleWord],
        bottomOffsetOverride: Double? = nil
    ) {
        self.id = id
        self.start = start
        self.end = end
        self.text = text
        self.words = words
        self.bottomOffsetOverride = bottomOffsetOverride
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case start
        case end
        case text
        case words
        case bottomOffsetOverride
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        start = try container.decode(Double.self, forKey: .start)
        end = try container.decode(Double.self, forKey: .end)
        text = try container.decode(String.self, forKey: .text)
        words = try container.decode([SubtitleWord].self, forKey: .words)
        bottomOffsetOverride = try container.decodeIfPresent(
            Double.self,
            forKey: .bottomOffsetOverride
        )
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(start, forKey: .start)
        try container.encode(end, forKey: .end)
        try container.encode(text, forKey: .text)
        try container.encode(words, forKey: .words)
        try container.encodeIfPresent(bottomOffsetOverride, forKey: .bottomOffsetOverride)
    }

    func contains(_ time: Double) -> Bool {
        time >= start && time < end
    }
}

struct SubtitleTimeline: Sendable {
    private let cues: [SubtitleCue]

    init(cues: [SubtitleCue]) {
        self.cues = cues.sorted { $0.start < $1.start }
    }

    func activeCue(at time: Double) -> SubtitleCue? {
        var lower = 0
        var upper = cues.count

        while lower < upper {
            let middle = (lower + upper) / 2
            if cues[middle].start <= time {
                lower = middle + 1
            } else {
                upper = middle
            }
        }

        guard lower > 0 else { return nil }
        let candidate = cues[lower - 1]
        return candidate.contains(time) ? candidate : nil
    }
}

struct MobileTranscriptionResult: Decodable, Equatable, Sendable {
    let requestId: String
    let durationSeconds: Double
    let creditsCharged: Int
    let balance: Int
    let paidBalance: Int
    let promotionalBalance: Int
    let reversalDebt: Int
    let aiSpendableBalance: Int
    let videoUploaded: Bool
    let serverMediaRetained: Bool
    let cues: [SubtitleCue]
    let hasAuthoritativeWalletSnapshot: Bool

    private enum CodingKeys: String, CodingKey {
        case requestId
        case durationSeconds
        case creditsCharged
        case balance
        case paidBalance
        case promotionalBalance
        case reversalDebt
        case aiSpendableBalance
        case videoUploaded
        case serverMediaRetained
        case cues
    }

    init(
        requestId: String,
        durationSeconds: Double,
        creditsCharged: Int,
        balance: Int,
        paidBalance: Int? = nil,
        promotionalBalance: Int = 0,
        reversalDebt: Int = 0,
        aiSpendableBalance: Int? = nil,
        videoUploaded: Bool,
        serverMediaRetained: Bool,
        cues: [SubtitleCue]
    ) {
        let resolvedPaidBalance = paidBalance ?? balance
        self.requestId = requestId
        self.durationSeconds = durationSeconds
        self.creditsCharged = creditsCharged
        self.balance = balance
        self.paidBalance = resolvedPaidBalance
        self.promotionalBalance = promotionalBalance
        self.reversalDebt = reversalDebt
        self.aiSpendableBalance =
            aiSpendableBalance
            ?? (reversalDebt > 0 ? 0 : resolvedPaidBalance)
        self.videoUploaded = videoUploaded
        self.serverMediaRetained = serverMediaRetained
        self.cues = cues
        hasAuthoritativeWalletSnapshot = true
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        requestId = try container.decode(String.self, forKey: .requestId)
        durationSeconds = try container.decode(Double.self, forKey: .durationSeconds)
        creditsCharged = try container.decode(Int.self, forKey: .creditsCharged)
        balance = try container.decode(Int.self, forKey: .balance)
        let decodedPaid = try container.decodeIfPresent(Int.self, forKey: .paidBalance)
        let decodedPromotional = try container.decodeIfPresent(
            Int.self,
            forKey: .promotionalBalance
        )
        let decodedDebt = try container.decodeIfPresent(Int.self, forKey: .reversalDebt)
        let decodedSpendable = try container.decodeIfPresent(
            Int.self,
            forKey: .aiSpendableBalance
        )
        paidBalance = decodedPaid ?? balance
        promotionalBalance = decodedPromotional ?? max(0, balance - paidBalance)
        reversalDebt = decodedDebt ?? 0
        aiSpendableBalance =
            decodedSpendable
            ?? (reversalDebt > 0 ? 0 : paidBalance)
        videoUploaded = try container.decode(Bool.self, forKey: .videoUploaded)
        serverMediaRetained = try container.decode(Bool.self, forKey: .serverMediaRetained)
        cues = try container.decode([SubtitleCue].self, forKey: .cues)
        hasAuthoritativeWalletSnapshot =
            decodedPaid != nil
            && decodedPromotional != nil
            && decodedDebt != nil
            && decodedSpendable != nil
    }

    var wallet: PointsBalance {
        PointsBalance(
            balance: balance,
            paidBalance: paidBalance,
            promotionalBalance: promotionalBalance,
            reversalDebt: reversalDebt,
            aiSpendableBalance: aiSpendableBalance
        )
    }

    func replacingWallet(with wallet: PointsBalance) -> MobileTranscriptionResult {
        MobileTranscriptionResult(
            requestId: requestId,
            durationSeconds: durationSeconds,
            creditsCharged: creditsCharged,
            balance: wallet.balance,
            paidBalance: wallet.paidBalance,
            promotionalBalance: wallet.promotionalBalance,
            reversalDebt: wallet.reversalDebt,
            aiSpendableBalance: wallet.aiSpendableBalance,
            videoUploaded: videoUploaded,
            serverMediaRetained: serverMediaRetained,
            cues: cues
        )
    }
}

struct PointsBalance: Codable, Equatable, Sendable {
    let balance: Int
    let paidBalance: Int
    let promotionalBalance: Int
    let reversalDebt: Int
    let aiSpendableBalance: Int
}

struct SubtitleStyle: Codable, Equatable, Sendable {
    static let bottomOffsetRange = 0.06...0.72

    var fontScale = 1.0
    var bottomOffset = 0.12
    var foreground = SubtitleColor.yellow

    func resolvedBottomOffset(for cue: SubtitleCue) -> Double {
        min(
            max(cue.bottomOffsetOverride ?? bottomOffset, Self.bottomOffsetRange.lowerBound),
            Self.bottomOffsetRange.upperBound
        )
    }
}

enum SubtitleLayout {
    static let maximumTextWidthFraction: CGFloat = 0.84
    static let maximumCaptionWidthFraction: CGFloat = 0.88
    static let fontSizeFraction: CGFloat = 0.058
    static let verticalPaddingFraction: CGFloat = 0.018
    static let minimumFontScale: CGFloat = 0.72
    static let fontReductionStep: CGFloat = 0.04
    static let maximumLineCount = 3
    static let maximumLineHeightMultiplier: CGFloat = 3.05
    private static let layoutReferenceWidth: CGFloat = 1_000

    static func normalizedText(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
    }

    static func maximumTextWidth(frameWidth: CGFloat) -> CGFloat {
        max(1, frameWidth * maximumTextWidthFraction)
    }

    static func maximumCaptionWidth(frameWidth: CGFloat) -> CGFloat {
        max(1, frameWidth * maximumCaptionWidthFraction)
    }

    static func baseFontSize(frameWidth: CGFloat, scale: Double) -> CGFloat {
        max(1, frameWidth * fontSizeFraction * CGFloat(scale))
    }

    static func resolvedFontSize(
        text: String,
        frameWidth: CGFloat,
        scale: Double
    ) -> CGFloat {
        baseFontSize(frameWidth: frameWidth, scale: scale)
            * resolvedFontReduction(text: text, scale: scale)
    }

    static func verticalPadding(frameWidth: CGFloat) -> CGFloat {
        max(1, frameWidth * verticalPaddingFraction)
    }

    private static func resolvedFontReduction(text: String, scale: Double) -> CGFloat {
        let normalized = normalizedText(text)
        guard !normalized.isEmpty else { return 1 }
        let maximumWidth = maximumTextWidth(frameWidth: layoutReferenceWidth)
        let baseSize = baseFontSize(frameWidth: layoutReferenceWidth, scale: scale)
        var reduction: CGFloat = 1

        while true {
            let font = UIFont.systemFont(ofSize: baseSize * reduction, weight: .black)
            let paragraph = NSMutableParagraphStyle()
            paragraph.alignment = .center
            paragraph.lineBreakMode = .byWordWrapping
            let attributed = NSAttributedString(
                string: normalized,
                attributes: [
                    .font: font,
                    .paragraphStyle: paragraph,
                ]
            )
            let bounds = attributed.boundingRect(
                with: CGSize(width: maximumWidth, height: .greatestFiniteMagnitude),
                options: [.usesLineFragmentOrigin, .usesFontLeading],
                context: nil
            ).integral
            if bounds.height <= font.lineHeight * maximumLineHeightMultiplier
                || reduction <= minimumFontScale
            {
                return reduction
            }
            reduction = max(minimumFontScale, reduction - fontReductionStep)
        }
    }
}

enum SubtitlePlacement {
    static func bottomEdgeFromBottom(
        frameHeight: CGFloat,
        captionHeight: CGFloat,
        bottomOffset: Double
    ) -> CGFloat {
        let requested = frameHeight * CGFloat(bottomOffset)
        return min(max(requested, 0), max(0, frameHeight - captionHeight))
    }

    static func centerYFromTop(
        frameHeight: CGFloat,
        captionHeight: CGFloat,
        bottomOffset: Double
    ) -> CGFloat {
        let bottomEdge = bottomEdgeFromBottom(
            frameHeight: frameHeight,
            captionHeight: captionHeight,
            bottomOffset: bottomOffset
        )
        return frameHeight - bottomEdge - captionHeight / 2
    }
}

enum SubtitleColor: String, CaseIterable, Codable, Identifiable, Sendable {
    case yellow
    case white
    case cyan

    var id: String { rawValue }
}
