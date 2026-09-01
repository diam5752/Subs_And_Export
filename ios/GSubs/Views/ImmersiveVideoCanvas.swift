import AVFoundation
import SwiftUI
import UIKit

struct ImmersiveVideoCanvas: View {
    @Environment(\.isEnabled) private var isEnabled

    let videoURL: URL
    @Binding var cues: [SubtitleCue]
    let style: SubtitleStyle
    @Binding var selectedCueID: UUID?
    let focusedCueID: UUID?
    let subtitleFocus: FocusState<UUID?>.Binding

    @State private var player: AVPlayer
    @State private var activeCueID: UUID?
    @State private var isPlaying = false
    @State private var videoAspectRatio: CGFloat = 9.0 / 16.0
    @State private var draggedCueID: UUID?
    @State private var dragStartOffset: Double?
    @State private var dragFeedbackOffset: Double?
    @State private var transportSymbol: String?
    @State private var feedbackTask: Task<Void, Never>?
    @State private var transportTask: Task<Void, Never>?

    init(
        videoURL: URL,
        cues: Binding<[SubtitleCue]>,
        style: SubtitleStyle,
        selectedCueID: Binding<UUID?>,
        focusedCueID: UUID?,
        subtitleFocus: FocusState<UUID?>.Binding
    ) {
        self.videoURL = videoURL
        _cues = cues
        self.style = style
        _selectedCueID = selectedCueID
        self.focusedCueID = focusedCueID
        self.subtitleFocus = subtitleFocus
        _player = State(initialValue: AVPlayer(url: videoURL))
    }

    var body: some View {
        GeometryReader { proxy in
            let canvasSize = finiteSize(proxy.size)
            let videoFrame = fittedVideoFrame(in: canvasSize)

            ZStack {
                Color.black

                PlayerLayerSurface(player: player)
                    .contentShape(Rectangle())
                    .onTapGesture(perform: togglePlayback)
                    .accessibilityElement()
                    .accessibilityLabel("Βίντεο πλήρους οθόνης")
                    .accessibilityHint(
                        "Άγγιξε το βίντεο για αναπαραγωγή. Άγγιξε ή σύρε τον υπότιτλο για επεξεργασία."
                    )
                    .accessibilityIdentifier("video-preview")

                subtitleLayer(in: videoFrame)

                if let transportSymbol {
                    Image(systemName: transportSymbol)
                        .font(.system(size: 28, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(width: 68, height: 68)
                        .background(Color.black.opacity(0.54), in: Circle())
                        .transition(.scale.combined(with: .opacity))
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }

                if let dragFeedbackOffset {
                    Text("Θέση φράσης · \(positionPercentage(dragFeedbackOffset))%")
                        .font(.caption.monospacedDigit().weight(.bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 12)
                        .frame(minHeight: 34)
                        .background(Color.black.opacity(0.72), in: Capsule())
                        .frame(maxHeight: .infinity, alignment: .top)
                        .padding(.top, 58)
                        .transition(.move(edge: .top).combined(with: .opacity))
                        .allowsHitTesting(false)
                        .accessibilityIdentifier("drag-position-indicator")
                }

                VStack {
                    Spacer()
                    HStack {
                        Button(action: togglePlayback) {
                            Color.clear
                                .frame(width: 44, height: 44)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(isPlaying ? "Παύση" : "Αναπαραγωγή")
                        .accessibilityHint("Εναλλάσσει την αναπαραγωγή χωρίς να ανοίγει χειριστήρια.")
                        .accessibilityIdentifier("preview-playback-toggle")
                        Spacer()
                    }
                }
            }
            .coordinateSpace(name: "immersive-video-canvas")
            .frame(width: canvasSize.width, height: canvasSize.height)
        }
        .background(Color.black)
        .task(id: videoURL) {
            guard let loadedAspectRatio = await Self.displayAspectRatio(for: videoURL),
                !Task.isCancelled
            else {
                return
            }
            videoAspectRatio = loadedAspectRatio
        }
        .task(id: cues.map(\.id)) {
            await observePlayback()
        }
        .onAppear(perform: beginPlayback)
        .onChange(of: selectedCueID) { _, cueID in
            focusSelectionIfNeeded(cueID)
        }
        .onChange(of: focusedCueID) { _, cueID in
            if let cueID {
                selectedCueID = cueID
            }
        }
        .onChange(of: isEnabled) { _, enabled in
            if !enabled {
                player.pause()
            }
        }
        .onDisappear {
            feedbackTask?.cancel()
            transportTask?.cancel()
            player.pause()
        }
    }

    @ViewBuilder
    private func subtitleLayer(in videoFrame: CGRect) -> some View {
        if let index = displayedCueIndex {
            let cue = cues[index]
            ImmersiveSubtitlePositionLayout(
                bottomOffset: style.resolvedBottomOffset(for: cue)
            ) {
                editableSubtitle(
                    cue: cue,
                    index: index,
                    frameWidth: videoFrame.width,
                    frameHeight: videoFrame.height
                )
            }
            .frame(width: videoFrame.width, height: videoFrame.height)
            .position(x: videoFrame.midX, y: videoFrame.midY)
        }
    }

    private func editableSubtitle(
        cue: SubtitleCue,
        index: Int,
        frameWidth: CGFloat,
        frameHeight: CGFloat
    ) -> some View {
        let normalizedText = SubtitleLayout.normalizedText(cue.text)
        let fontSize = SubtitleLayout.resolvedFontSize(
            text: normalizedText,
            frameWidth: frameWidth,
            scale: style.fontScale
        )
        let isFocused = focusedCueID == cue.id
        let bottomOffset = style.resolvedBottomOffset(for: cue)

        return ZStack {
            TextField(
                "Υπότιτλος",
                text: textBinding(for: cue.id),
                axis: .vertical
            )
            .textFieldStyle(.plain)
            .font(.system(size: fontSize, weight: .black))
            .multilineTextAlignment(.center)
            .foregroundStyle(style.foreground.immersiveColor)
            .textInputAutocapitalization(.characters)
            .autocorrectionDisabled()
            .lineLimit(SubtitleLayout.maximumLineCount)
            .frame(width: SubtitleLayout.maximumTextWidth(frameWidth: frameWidth))
            .padding(.horizontal, 8)
            .padding(.vertical, SubtitleLayout.verticalPadding(frameWidth: frameWidth))
            .background(
                isFocused ? Color.black.opacity(0.44) : Color.clear,
                in: RoundedRectangle(cornerRadius: 8, style: .continuous)
            )
            .focused(subtitleFocus, equals: cue.id)
            .allowsHitTesting(isFocused)
            .accessibilityHidden(!isFocused)
            .accessibilityLabel("Κείμενο υποτίτλου \(index + 1)")
            .accessibilityHint("Διπλό άγγιγμα για διόρθωση.")
            .accessibilityValue("\(cue.text), θέση \(positionPercentage(bottomOffset))%")
            .accessibilityIdentifier(
                isFocused ? "subtitle-cue-\(index)" : "subtitle-editing-field-\(index)"
            )
        }
        .overlay {
            if isFocused {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(GSubsTheme.cyan, lineWidth: 1.5)
                    .allowsHitTesting(false)
            } else {
                Color.clear
                    .contentShape(Rectangle())
                    .gesture(subtitleInteractionGesture(for: cue.id, frameHeight: frameHeight))
                    .accessibilityElement()
                    .accessibilityAddTraits(.isButton)
                    .accessibilityLabel("Κείμενο υποτίτλου \(index + 1)")
                    .accessibilityHint(
                        "Διπλό άγγιγμα για διόρθωση. Σύρε πάνω ή κάτω για να μετακινήσεις μόνο αυτή τη φράση."
                    )
                    .accessibilityValue("\(cue.text), θέση \(positionPercentage(bottomOffset))%")
                    .accessibilityIdentifier("subtitle-cue-\(index)")
                    .accessibilityAction(.default) {
                        selectedCueID = cue.id
                        subtitleFocus.wrappedValue = cue.id
                    }
                    .accessibilityAdjustableAction { direction in
                        switch direction {
                        case .increment:
                            adjustPosition(of: cue.id, by: 0.03)
                        case .decrement:
                            adjustPosition(of: cue.id, by: -0.03)
                        @unknown default:
                            break
                        }
                    }
            }
        }
        .shadow(color: .black.opacity(0.95), radius: 1, x: 2, y: 2)
        .contentShape(Rectangle())
    }

    private func subtitleInteractionGesture(for cueID: UUID, frameHeight: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 0, coordinateSpace: .named("immersive-video-canvas"))
            .onChanged { value in
                let distance = hypot(value.translation.width, value.translation.height)
                guard distance >= 9 || draggedCueID == cueID else { return }
                guard let index = cues.firstIndex(where: { $0.id == cueID }) else { return }
                if draggedCueID != cueID {
                    subtitleFocus.wrappedValue = nil
                    selectedCueID = cueID
                    draggedCueID = cueID
                    dragStartOffset = style.resolvedBottomOffset(for: cues[index])
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                }
                guard let dragStartOffset else { return }
                let height = max(1, frameHeight)
                let delta = -Double(value.translation.height / height)
                let newOffset = clampedOffset(dragStartOffset + delta)
                cues[index].bottomOffsetOverride = newOffset
                withAnimation(.easeOut(duration: 0.12)) {
                    dragFeedbackOffset = newOffset
                }
            }
            .onEnded { value in
                let distance = hypot(value.translation.width, value.translation.height)
                guard distance >= 9 else {
                    selectedCueID = cueID
                    subtitleFocus.wrappedValue = cueID
                    return
                }
                draggedCueID = nil
                dragStartOffset = nil
                hideDragFeedbackAfterDelay()
            }
    }

    private var displayedCueIndex: Int? {
        let cueID: UUID?
        if let draggedCueID {
            cueID = draggedCueID
        } else if let focusedCueID {
            cueID = focusedCueID
        } else if isPlaying {
            cueID = activeCueID
        } else {
            cueID = selectedCueID ?? activeCueID ?? cues.first?.id
        }
        guard let cueID else { return nil }
        return cues.firstIndex(where: { $0.id == cueID })
    }

    private func textBinding(for cueID: UUID) -> Binding<String> {
        Binding(
            get: {
                cues.first(where: { $0.id == cueID })?.text ?? ""
            },
            set: { newValue in
                guard let index = cues.firstIndex(where: { $0.id == cueID }) else { return }
                cues[index].text = newValue
            }
        )
    }

    private func adjustPosition(of cueID: UUID, by change: Double) {
        guard let index = cues.firstIndex(where: { $0.id == cueID }) else { return }
        let current = style.resolvedBottomOffset(for: cues[index])
        let newOffset = clampedOffset(current + change)
        cues[index].bottomOffsetOverride = newOffset
        dragFeedbackOffset = newOffset
        hideDragFeedbackAfterDelay()
    }

    private func beginPlayback() {
        if selectedCueID == nil {
            selectedCueID = cues.first?.id
        }
        if let firstCue = cues.first {
            player.seek(
                to: CMTime(seconds: firstCue.start, preferredTimescale: 600),
                toleranceBefore: .zero,
                toleranceAfter: .zero
            )
        }
        player.play()
    }

    private func observePlayback() async {
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

    private func focusSelectionIfNeeded(_ cueID: UUID?) {
        guard focusedCueID == nil,
            draggedCueID == nil,
            cueID != activeCueID,
            let cueID,
            let cue = cues.first(where: { $0.id == cueID })
        else {
            return
        }
        player.pause()
        player.seek(
            to: CMTime(seconds: cue.start, preferredTimescale: 600),
            toleranceBefore: .zero,
            toleranceAfter: .zero
        )
    }

    private func togglePlayback() {
        let symbol: String
        if player.timeControlStatus == .playing {
            player.pause()
            symbol = "pause.fill"
        } else {
            player.play()
            symbol = "play.fill"
        }
        transportTask?.cancel()
        withAnimation(.spring(response: 0.24, dampingFraction: 0.82)) {
            transportSymbol = symbol
        }
        transportTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(620))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.18)) {
                transportSymbol = nil
            }
        }
    }

    private func hideDragFeedbackAfterDelay() {
        feedbackTask?.cancel()
        feedbackTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(780))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.18)) {
                dragFeedbackOffset = nil
            }
        }
    }

    private func clampedOffset(_ offset: Double) -> Double {
        min(
            max(offset, SubtitleStyle.bottomOffsetRange.lowerBound),
            SubtitleStyle.bottomOffsetRange.upperBound
        )
    }

    private func positionPercentage(_ offset: Double) -> Int {
        Int((offset * 100).rounded())
    }

    private func fittedVideoFrame(in size: CGSize) -> CGRect {
        guard size.width > 0, size.height > 0 else { return .zero }
        let frame = AVMakeRect(
            aspectRatio: CGSize(width: max(videoAspectRatio, 0.01), height: 1),
            insideRect: CGRect(origin: .zero, size: size)
        )
        guard frame.origin.x.isFinite,
            frame.origin.y.isFinite,
            frame.width.isFinite,
            frame.height.isFinite
        else {
            return CGRect(origin: .zero, size: size)
        }
        return frame
    }

    private func finiteSize(_ size: CGSize) -> CGSize {
        CGSize(
            width: size.width.isFinite ? max(0, size.width) : 0,
            height: size.height.isFinite ? max(0, size.height) : 0
        )
    }

    private static func displayAspectRatio(for url: URL) async -> CGFloat? {
        let asset = AVURLAsset(url: url)
        do {
            guard let track = try await asset.loadTracks(withMediaType: .video).first else {
                return nil
            }
            async let naturalSize = track.load(.naturalSize)
            async let preferredTransform = track.load(.preferredTransform)
            let bounds = CGRect(origin: .zero, size: try await naturalSize)
                .applying(try await preferredTransform)
                .standardized
            guard bounds.width.isFinite,
                bounds.height.isFinite,
                bounds.width > 0,
                bounds.height > 0
            else {
                return nil
            }
            return bounds.width / bounds.height
        } catch {
            return nil
        }
    }
}

private struct PlayerLayerSurface: UIViewRepresentable {
    let player: AVPlayer

    func makeUIView(context: Context) -> PlayerView {
        let view = PlayerView()
        view.playerLayer.videoGravity = .resizeAspect
        view.playerLayer.player = player
        return view
    }

    func updateUIView(_ view: PlayerView, context: Context) {
        if view.playerLayer.player !== player {
            view.playerLayer.player = player
        }
    }

    final class PlayerView: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }

        var playerLayer: AVPlayerLayer {
            guard let playerLayer = layer as? AVPlayerLayer else {
                preconditionFailure("PlayerView must use AVPlayerLayer")
            }
            return playerLayer
        }

        override init(frame: CGRect) {
            super.init(frame: frame)
            backgroundColor = .black
        }

        @available(*, unavailable)
        required init?(coder: NSCoder) {
            nil
        }
    }
}

private struct ImmersiveSubtitlePositionLayout: Layout {
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
    fileprivate var immersiveColor: Color {
        switch self {
        case .yellow: .yellow
        case .white: .white
        case .cyan: .cyan
        }
    }
}
