import Foundation

struct ProjectDraft: Codable, Equatable, Sendable {
    static let currentSchemaVersion = 1

    enum DurablePhase: String, Codable, Sendable {
        case ready
        case editing
    }

    let schemaVersion: Int
    let projectID: UUID
    let revision: UInt64
    let ownerUserID: String
    let sourceRelativePath: String
    let previewRelativePath: String?
    let duration: Double
    let cues: [SubtitleCue]
    let style: SubtitleStyle
    let transcriptionKey: String
    let phase: DurablePhase

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case projectID
        case revision
        case ownerUserID
        case sourceRelativePath
        case previewRelativePath
        case duration
        case cues
        case style
        case transcriptionKey
        case phase
    }

    init(
        schemaVersion: Int = currentSchemaVersion,
        projectID: UUID,
        revision: UInt64,
        ownerUserID: String,
        sourceRelativePath: String,
        previewRelativePath: String?,
        duration: Double,
        cues: [SubtitleCue],
        style: SubtitleStyle,
        transcriptionKey: String,
        phase: DurablePhase
    ) {
        self.schemaVersion = schemaVersion
        self.projectID = projectID
        self.revision = revision
        self.ownerUserID = ownerUserID
        self.sourceRelativePath = sourceRelativePath
        self.previewRelativePath = previewRelativePath
        self.duration = duration
        self.cues = cues
        self.style = style
        self.transcriptionKey = transcriptionKey
        self.phase = phase
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(Int.self, forKey: .schemaVersion)
        projectID = try container.decode(UUID.self, forKey: .projectID)
        revision = try container.decode(UInt64.self, forKey: .revision)
        ownerUserID = try container.decode(String.self, forKey: .ownerUserID)
        sourceRelativePath = try container.decode(String.self, forKey: .sourceRelativePath)
        previewRelativePath = try container.decodeIfPresent(
            String.self,
            forKey: .previewRelativePath
        )
        duration = try container.decode(Double.self, forKey: .duration)
        cues = try container.decode([PersistedSubtitleCue].self, forKey: .cues).map(\.cue)
        style = try container.decode(SubtitleStyle.self, forKey: .style)
        transcriptionKey = try container.decode(String.self, forKey: .transcriptionKey)
        phase = try container.decode(DurablePhase.self, forKey: .phase)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(projectID, forKey: .projectID)
        try container.encode(revision, forKey: .revision)
        try container.encode(ownerUserID, forKey: .ownerUserID)
        try container.encode(sourceRelativePath, forKey: .sourceRelativePath)
        try container.encodeIfPresent(previewRelativePath, forKey: .previewRelativePath)
        try container.encode(duration, forKey: .duration)
        try container.encode(cues.map(PersistedSubtitleCue.init), forKey: .cues)
        try container.encode(style, forKey: .style)
        try container.encode(transcriptionKey, forKey: .transcriptionKey)
        try container.encode(phase, forKey: .phase)
    }

    func updating(
        revision: UInt64,
        cues: [SubtitleCue],
        style: SubtitleStyle,
        transcriptionKey: String,
        phase: DurablePhase
    ) -> ProjectDraft {
        ProjectDraft(
            projectID: projectID,
            revision: revision,
            ownerUserID: ownerUserID,
            sourceRelativePath: sourceRelativePath,
            previewRelativePath: previewRelativePath,
            duration: duration,
            cues: cues,
            style: style,
            transcriptionKey: transcriptionKey,
            phase: phase
        )
    }
}

private struct PersistedSubtitleCue: Codable {
    let id: UUID
    let start: Double
    let end: Double
    let text: String
    let words: [SubtitleWord]
    let bottomOffsetOverride: Double?

    init(_ cue: SubtitleCue) {
        id = cue.id
        start = cue.start
        end = cue.end
        text = cue.text
        words = cue.words
        bottomOffsetOverride = cue.bottomOffsetOverride
    }

    var cue: SubtitleCue {
        SubtitleCue(
            id: id,
            start: start,
            end: end,
            text: text,
            words: words,
            bottomOffsetOverride: bottomOffsetOverride
        )
    }
}

struct RestoredProjectDraft: Equatable, Sendable {
    let draft: ProjectDraft
    let sourceURL: URL
    let previewURL: URL
}

enum ProjectDraftError: LocalizedError, Equatable, Sendable {
    case corrupt
    case ownerMismatch
    case staleRevision

    var errorDescription: String? {
        switch self {
        case .corrupt:
            "Το αποθηκευμένο πρόχειρο δεν ήταν ασφαλές και αφαιρέθηκε."
        case .ownerMismatch:
            "Το αποθηκευμένο πρόχειρο ανήκε σε διαφορετικό λογαριασμό και αφαιρέθηκε."
        case .staleRevision:
            "Αγνοήθηκε παλαιότερη έκδοση του πρόχειρου."
        }
    }
}

enum ProjectDraftValidator {
    static let maximumManifestBytes = 2 * 1_024 * 1_024
    private static let maximumCueCount = 10_000
    private static let maximumWordCount = 50_000
    private static let timingTolerance = 1.0

    static func validate(_ draft: ProjectDraft) throws {
        guard draft.schemaVersion == ProjectDraft.currentSchemaVersion,
            draft.revision > 0,
            isValidOwner(draft.ownerUserID),
            isValidDuration(draft.duration),
            isValidTranscriptionKey(draft.transcriptionKey),
            isValidStyle(draft.style),
            isValidPhase(draft)
        else {
            throw ProjectDraftError.corrupt
        }
        try validateCues(draft.cues, duration: draft.duration)
    }

    private static func isValidOwner(_ owner: String) -> Bool {
        !owner.isEmpty
            && owner.count <= 256
            && owner == owner.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func isValidDuration(_ duration: Double) -> Bool {
        duration.isFinite && duration > 0 && duration <= AudioExtractor.maximumDuration
    }

    private static func isValidTranscriptionKey(_ key: String) -> Bool {
        guard (16...128).contains(key.count) else { return false }
        return key.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0) || $0 == "-" || $0 == "_"
        }
    }

    private static func isValidStyle(_ style: SubtitleStyle) -> Bool {
        style.fontScale.isFinite
            && (0.75...1.35).contains(style.fontScale)
            && style.bottomOffset.isFinite
            && SubtitleStyle.bottomOffsetRange.contains(style.bottomOffset)
    }

    private static func isValidPhase(_ draft: ProjectDraft) -> Bool {
        switch draft.phase {
        case .ready:
            draft.cues.isEmpty
        case .editing:
            !draft.cues.isEmpty
        }
    }

    private static func validateCues(
        _ cues: [SubtitleCue],
        duration: Double
    ) throws {
        guard cues.count <= maximumCueCount,
            Set(cues.map(\.id)).count == cues.count,
            cues.reduce(0, { $0 + $1.words.count }) <= maximumWordCount
        else {
            throw ProjectDraftError.corrupt
        }
        for cue in cues {
            guard validTiming(cue.start, cue.end, duration: duration),
                cue.text.utf8.count <= 16_000,
                validOffset(cue.bottomOffsetOverride),
                cue.words.allSatisfy({
                    validWord(
                        $0,
                        cueStart: cue.start,
                        cueEnd: cue.end,
                        duration: duration
                    )
                })
            else {
                throw ProjectDraftError.corrupt
            }
        }
    }

    private static func validWord(
        _ word: SubtitleWord,
        cueStart: Double,
        cueEnd: Double,
        duration: Double
    ) -> Bool {
        validTiming(word.start, word.end, duration: duration)
            && word.start >= cueStart - timingTolerance
            && word.end <= cueEnd + timingTolerance
            && word.text.utf8.count <= 4_000
    }

    private static func validTiming(
        _ start: Double,
        _ end: Double,
        duration: Double
    ) -> Bool {
        start.isFinite
            && end.isFinite
            && start >= 0
            && end > start
            && end <= duration + timingTolerance
    }

    private static func validOffset(_ offset: Double?) -> Bool {
        guard let offset else { return true }
        return offset.isFinite && SubtitleStyle.bottomOffsetRange.contains(offset)
    }
}
