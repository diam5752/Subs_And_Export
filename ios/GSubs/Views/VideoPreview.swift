import AVFoundation
import AVKit
import SwiftUI

struct VideoPreview: View {
    @Environment(\.isEnabled) private var isEnabled

    let videoURL: URL
    let cues: [SubtitleCue]
    let style: SubtitleStyle
    let selectedCueID: UUID?
    let maximumHeight: CGFloat
    let showsPlaybackControl: Bool

    @State private var player: AVPlayer
    @State private var activeCueID: UUID?
    @State private var isPlaying = false
    @State private var videoAspectRatio: CGFloat = 9.0 / 16.0
    private let cornerRadius = 26.0

    // Very tall clips stay usable inside the editor while the video itself
    // keeps its real aspect ratio and is letterboxed within the preview.
    private var previewAspectRatio: CGFloat {
        max(videoAspectRatio, 0.72)
    }

    init(
        videoURL: URL,
        cues: [SubtitleCue],
        style: SubtitleStyle,
        selectedCueID: UUID? = nil,
        maximumHeight: CGFloat = 500,
        showsPlaybackControl: Bool = true
    ) {
        self.videoURL = videoURL
        self.cues = cues
        self.style = style
        self.selectedCueID = selectedCueID
        self.maximumHeight = maximumHeight
        self.showsPlaybackControl = showsPlaybackControl
        _player = State(initialValue: AVPlayer(url: videoURL))
        _activeCueID = State(initialValue: selectedCueID)
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)

        ZStack {
            shape
                .fill(Color.black)

            VideoPlayer(player: player) {
                GeometryReader { proxy in
                    if let cue = cues.first(where: { $0.id == displayedCueID }) {
                        PositionedSubtitlePreview(
                            cue: cue,
                            style: style,
                            frameSize: proxy.size
                        )
                    }
                }
            }
            .aspectRatio(videoAspectRatio, contentMode: .fit)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.black)

            if showsPlaybackControl {
                VStack {
                    HStack {
                        Button(action: togglePlayback) {
                            Image(systemName: isPlaying ? "pause.fill" : "play.fill")
                                .font(.system(size: 15, weight: .bold))
                                .foregroundStyle(.white)
                                .frame(width: 44, height: 44)
                                .background(Color.black.opacity(0.62), in: Circle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(isPlaying ? "Παύση" : "Αναπαραγωγή")
                        .accessibilityIdentifier("preview-playback-toggle")
                        Spacer()
                    }
                    Spacer()
                }
                .padding(12)
            }
        }
        .aspectRatio(previewAspectRatio, contentMode: .fit)
        .frame(maxWidth: .infinity)
        .frame(maxHeight: maximumHeight)
        .clipShape(shape)
        .overlay {
            shape.strokeBorder(GSubsTheme.border, lineWidth: 1)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("video-preview")
        .accessibilityLabel("Προεπισκόπηση βίντεο")
        .accessibilityHint(
            showsPlaybackControl
                ? "Χρησιμοποίησε τα χειριστήρια για αναπαραγωγή και μετακίνηση στο βίντεο."
                : "Δείχνει την επιλεγμένη φράση ενώ γράφεις."
        )
        .task(id: videoURL) {
            guard let loadedAspectRatio = await Self.displayAspectRatio(for: videoURL),
                !Task.isCancelled
            else {
                return
            }
            videoAspectRatio = loadedAspectRatio
        }
        .task(id: cues.map(\.id)) {
            let timeline = SubtitleTimeline(cues: cues)
            while !Task.isCancelled {
                let seconds = player.currentTime().seconds
                let cueID = seconds.isFinite ? timeline.activeCue(at: seconds)?.id : nil
                if activeCueID != cueID {
                    activeCueID = cueID
                }
                let playerIsPlaying = player.timeControlStatus == .playing
                if isPlaying != playerIsPlaying {
                    isPlaying = playerIsPlaying
                }
                try? await Task.sleep(for: .milliseconds(120))
            }
        }
        .onAppear(perform: focusSelectedCue)
        .onChange(of: selectedCueID) { _, _ in
            focusSelectedCue()
        }
        .onChange(of: isEnabled) { _, enabled in
            if !enabled {
                focusSelectedCue()
            }
        }
        .onDisappear { player.pause() }
    }

    private var displayedCueID: UUID? {
        isPlaying ? activeCueID : (selectedCueID ?? activeCueID)
    }

    private func focusSelectedCue() {
        guard let selectedCueID,
            let cue = cues.first(where: { $0.id == selectedCueID })
        else {
            return
        }
        player.pause()
        isPlaying = false
        activeCueID = selectedCueID
        player.seek(
            to: CMTime(seconds: cue.start, preferredTimescale: 600),
            toleranceBefore: .zero,
            toleranceAfter: .zero
        )
    }

    private func togglePlayback() {
        if player.timeControlStatus == .playing {
            player.pause()
        } else {
            player.play()
        }
    }

    private static func displayAspectRatio(for url: URL) async -> CGFloat? {
        let asset = AVURLAsset(url: url)

        do {
            guard let track = try await asset.loadTracks(withMediaType: .video).first else {
                return nil
            }
            async let naturalSize = track.load(.naturalSize)
            async let preferredTransform = track.load(.preferredTransform)
            let transformedBounds = CGRect(origin: .zero, size: try await naturalSize)
                .applying(try await preferredTransform)
                .standardized
            let width = transformedBounds.width
            let height = transformedBounds.height

            guard width.isFinite, height.isFinite, width > 0, height > 0 else {
                return nil
            }
            return width / height
        } catch {
            return nil
        }
    }
}

private struct PositionedSubtitlePreview: View {
    let cue: SubtitleCue
    let style: SubtitleStyle
    let frameSize: CGSize

    var body: some View {
        let bottomOffset = style.resolvedBottomOffset(for: cue)
        let normalizedText = SubtitleLayout.normalizedText(cue.text)
        let fontSize = SubtitleLayout.resolvedFontSize(
            text: normalizedText,
            frameWidth: frameSize.width,
            scale: style.fontScale
        )
        let verticalPadding = SubtitleLayout.verticalPadding(frameWidth: frameSize.width)
        SubtitlePositionLayout(bottomOffset: bottomOffset) {
            Text(normalizedText)
                .font(.system(size: fontSize, weight: .black))
                .multilineTextAlignment(.center)
                .foregroundStyle(style.foreground.color)
                .shadow(color: .black.opacity(0.95), radius: 1, x: 2, y: 2)
                .lineLimit(SubtitleLayout.maximumLineCount)
                .frame(width: SubtitleLayout.maximumTextWidth(frameWidth: frameSize.width))
                .padding(.vertical, verticalPadding)
                .accessibilityLabel("Τρέχων υπότιτλος: \(cue.text)")
                .accessibilityValue("Θέση \(Int((bottomOffset * 100).rounded()))%")
                .accessibilityIdentifier("active-subtitle")
        }
        .frame(width: frameSize.width, height: frameSize.height)
    }
}

private struct SubtitlePositionLayout: Layout {
    let bottomOffset: Double

    func sizeThatFits(
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) -> CGSize {
        proposal.replacingUnspecifiedDimensions()
    }

    func placeSubviews(
        in bounds: CGRect,
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) {
        guard let subtitle = subviews.first else { return }
        let subtitleSize = subtitle.sizeThatFits(
            ProposedViewSize(width: bounds.width, height: nil)
        )
        let centerY = SubtitlePlacement.centerYFromTop(
            frameHeight: bounds.height,
            captionHeight: subtitleSize.height,
            bottomOffset: bottomOffset
        )
        subtitle.place(
            at: CGPoint(x: bounds.midX, y: bounds.minY + centerY),
            anchor: .center,
            proposal: ProposedViewSize(subtitleSize)
        )
    }
}

extension SubtitleColor {
    fileprivate var color: Color {
        switch self {
        case .yellow: .yellow
        case .white: .white
        case .cyan: .cyan
        }
    }
}
