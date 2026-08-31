import SwiftUI

extension StudioView {
    func mobileSubtitleEditor(videoURL: URL) -> some View {
        GeometryReader { proxy in
            if proxy.size.width > 500 {
                mobileLandscapeEditor(videoURL: videoURL, size: proxy.size)
            } else {
                mobilePortraitEditor(videoURL: videoURL, size: proxy.size)
            }
        }
        .overlay(alignment: .topLeading) {
            Color.clear
                .frame(width: 1, height: 1)
                .accessibilityElement()
                .accessibilityLabel("Editor υποτίτλων")
                .accessibilityIdentifier("mobile-editor")
                .allowsHitTesting(false)
        }
        .disabled(model.isProjectOperationInFlight)
    }

    private func mobilePortraitEditor(videoURL: URL, size: CGSize) -> some View {
        let previewHeight = mobilePreviewHeight(
            availableHeight: size.height,
            keyboardIsVisible: keyboardIsVisible
        )

        return VStack(spacing: keyboardIsVisible ? 2 : 6) {
            mobileEditorHeader
                .frame(height: keyboardIsVisible ? 0 : 44)
                .opacity(keyboardIsVisible ? 0 : 1)
                .clipped()
                .accessibilityHidden(keyboardIsVisible)
                .allowsHitTesting(!keyboardIsVisible)
            mobileVideoPreview(
                videoURL: videoURL,
                height: previewHeight,
                showsPlaybackControl: !keyboardIsVisible
            )
            cueNavigation
                .frame(height: keyboardIsVisible ? 0 : 44)
                .opacity(keyboardIsVisible ? 0 : 1)
                .clipped()
                .accessibilityHidden(keyboardIsVisible)
                .allowsHitTesting(!keyboardIsVisible)
            mobileControlPanel(compactKeyboard: keyboardIsVisible)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    @ViewBuilder
    private func mobileLandscapeEditor(videoURL: URL, size: CGSize) -> some View {
        if model.cues.indices.contains(selectedCueIndex) {
            HStack(alignment: .top, spacing: keyboardIsVisible ? 8 : 10) {
                mobileVideoPreview(
                    videoURL: videoURL,
                    height: keyboardIsVisible
                        ? max(80, size.height - 8)
                        : max(120, size.height - 12),
                    showsPlaybackControl: !keyboardIsVisible
                )
                .frame(
                    width: keyboardIsVisible
                        ? min(122, size.width * 0.20)
                        : size.width * 0.34
                )
                VStack(spacing: 8) {
                    closeVideoButton
                    accountMenu
                }
                .frame(width: keyboardIsVisible ? 0 : 44)
                .opacity(keyboardIsVisible ? 0 : 1)
                .clipped()
                .accessibilityHidden(keyboardIsVisible)
                .allowsHitTesting(!keyboardIsVisible)
                VStack(spacing: keyboardIsVisible ? 2 : 4) {
                    if model.exportedURL != nil {
                        mobileExportResult
                    } else {
                        cueNavigation
                            .frame(height: keyboardIsVisible ? 0 : 44)
                            .opacity(keyboardIsVisible ? 0 : 1)
                            .clipped()
                            .accessibilityHidden(keyboardIsVisible)
                            .allowsHitTesting(!keyboardIsVisible)
                        mobileLandscapeEditControls(at: selectedCueIndex)
                    }
                }
            }
            .padding(keyboardIsVisible ? 4 : 6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
    }

    private func mobileVideoPreview(
        videoURL: URL,
        height: CGFloat,
        showsPlaybackControl: Bool = true
    ) -> some View {
        VideoPreview(
            videoURL: model.previewURL ?? videoURL,
            cues: model.cues,
            style: model.style,
            selectedCueID: selectedCueIDForPreview,
            maximumHeight: height,
            showsPlaybackControl: showsPlaybackControl
        )
        .id(videoURL)
        .frame(maxWidth: .infinity)
        .frame(height: height)
    }

    func compactStatus(_ text: String, icon: String, tint: Color) -> some View {
        Label(text, systemImage: icon)
            .font(.caption.weight(.semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.7)
            .padding(.horizontal, 9)
            .frame(maxWidth: .infinity, minHeight: 30)
            .foregroundStyle(.primary)
            .background(GSubsTheme.surface.opacity(0.94), in: Capsule())
            .overlay(Capsule().stroke(tint.opacity(0.35)))
    }

    private var cueNavigation: some View {
        HStack(spacing: 10) {
            Button(action: selectPreviousCue) {
                Image(systemName: "chevron.left")
                    .font(.subheadline.weight(.bold))
                    .frame(width: 44, height: 44)
                    .background(GSubsTheme.elevated, in: Circle())
            }
            .buttonStyle(.plain)
            .disabled(selectedCueIndex <= 0)
            .accessibilityLabel("Προηγούμενος υπότιτλος από τον \(selectedCueIndex + 1)")
            .accessibilityHint("Μεταφέρει το preview και το πεδίο στην προηγούμενη φράση.")
            .accessibilityIdentifier("cue-previous")

            Menu {
                ForEach(model.cues.indices, id: \.self) { index in
                    Button {
                        selectCue(at: index)
                    } label: {
                        Label {
                            Text("\(index + 1) · \(model.cues[index].text)")
                                .lineLimit(1)
                        } icon: {
                            Image(systemName: index == selectedCueIndex ? "checkmark" : "captions.bubble")
                        }
                    }
                    .accessibilityIdentifier("cue-picker-item-\(index)")
                }
            } label: {
                VStack(spacing: 1) {
                    HStack(spacing: 4) {
                        Text("\(selectedCueIndex + 1) / \(model.cues.count)")
                            .font(.subheadline.monospacedDigit().weight(.bold))
                        Image(systemName: "chevron.down")
                            .font(.caption2.weight(.bold))
                    }
                    if model.cues.indices.contains(selectedCueIndex) {
                        Text(
                            "\(time(model.cues[selectedCueIndex].start)) – \(time(model.cues[selectedCueIndex].end))"
                        )
                        .font(.caption2.monospacedDigit().weight(.medium))
                        .foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Υπότιτλος \(selectedCueIndex + 1) από \(model.cues.count)")
            .accessibilityHint("Ανοίγει γρήγορη επιλογή οποιασδήποτε φράσης.")
            .accessibilityIdentifier("cue-counter")

            Button(action: selectNextCue) {
                Image(systemName: "chevron.right")
                    .font(.subheadline.weight(.bold))
                    .frame(width: 44, height: 44)
                    .background(GSubsTheme.elevated, in: Circle())
            }
            .buttonStyle(.plain)
            .disabled(selectedCueIndex >= model.cues.count - 1)
            .accessibilityLabel("Επόμενος υπότιτλος από τον \(selectedCueIndex + 1)")
            .accessibilityHint("Μεταφέρει το preview και το πεδίο στην επόμενη φράση.")
            .accessibilityIdentifier("cue-next")
        }
        .dynamicTypeSize(...DynamicTypeSize.large)
    }

    @ViewBuilder
    private func mobileControlPanel(compactKeyboard: Bool = false) -> some View {
        if model.exportedURL != nil {
            mobileExportResult
        } else if model.cues.indices.contains(selectedCueIndex) {
            mobileEditControls(at: selectedCueIndex, compactKeyboard: compactKeyboard)
        }
    }

    private func mobileEditControls(
        at index: Int,
        compactKeyboard: Bool = false
    ) -> some View {
        VStack(spacing: compactKeyboard ? 2 : 5) {
            TextField("Υπότιτλος", text: $model.cues[index].text, axis: .vertical)
                .font(.callout.weight(.medium))
                .lineLimit(
                    dynamicTypeSize.isAccessibilitySize ? 1 : 2,
                    reservesSpace: true
                )
                .focused($focusedCueID, equals: model.cues[index].id)
                .padding(.horizontal, 10)
                .frame(minHeight: 44)
                .background(GSubsTheme.elevated, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(GSubsTheme.border))
                .accessibilityLabel("Κείμενο υποτίτλου \(index + 1)")
                .accessibilityIdentifier("subtitle-cue-\(index)")
                .simultaneousGesture(TapGesture().onEnded { focusCue(at: index) })
                .id(model.cues[index].id)

            HStack(spacing: 7) {
                Text("Θέση φράσης")
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                Slider(
                    value: cuePositionBinding(at: index),
                    in: SubtitleStyle.bottomOffsetRange
                )
                .tint(GSubsTheme.cyan)
                .accessibilityLabel("Θέση υποτίτλου \(index + 1)")
                .accessibilityHint("Αλλάζει μόνο τη θέση αυτής της φράσης.")
                .accessibilityIdentifier("cue-position-slider-\(index)")
                cuePositionModeButton(at: index)
                if model.cues[index].bottomOffsetOverride != nil {
                    Button {
                        model.cues[index].bottomOffsetOverride = nil
                    } label: {
                        Image(systemName: "arrow.uturn.backward")
                            .font(.caption.weight(.bold))
                            .frame(width: 44, height: 44)
                            .background(GSubsTheme.cyan.opacity(0.10), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(GSubsTheme.cyan)
                    .accessibilityLabel("Επαναφορά υποτίτλου \(index + 1) στην κοινή θέση")
                    .accessibilityHint("Αφαιρεί μόνο την ξεχωριστή θέση αυτής της φράσης.")
                    .accessibilityIdentifier("cue-position-reset-\(index)")
                }
            }
            .frame(minHeight: 44)
            .dynamicTypeSize(...DynamicTypeSize.large)

            Divider().overlay(GSubsTheme.border)

            globalSizeAndColorControls
                .dynamicTypeSize(...DynamicTypeSize.large)

            HStack(spacing: 8) {
                Text("Θέση όλων")
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Slider(value: $model.style.bottomOffset, in: SubtitleStyle.bottomOffsetRange)
                    .tint(GSubsTheme.cyan)
                    .accessibilityLabel("Θέση όλων των υποτίτλων")
                    .accessibilityIdentifier("global-position-slider")
                Text(positionLabel(for: model.style.bottomOffset))
                    .font(.caption.monospacedDigit().weight(.semibold))
                    .lineLimit(1)
                    .frame(minWidth: 46, alignment: .trailing)
            }
            .frame(minHeight: 44)
            .dynamicTypeSize(...DynamicTypeSize.large)
        }
        .padding(compactKeyboard ? 5 : 8)
        .background(GSubsTheme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(GSubsTheme.border))
    }

    @ViewBuilder
    private var globalSizeAndColorControls: some View {
        if dynamicTypeSize.isAccessibilitySize {
            VStack(spacing: 2) {
                HStack(spacing: 4) {
                    fontScaleControls
                    Spacer(minLength: 0)
                }
                HStack(spacing: 4) {
                    Text("Χρώμα")
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    subtitleColorControls
                }
            }
        } else {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 4) {
                    fontScaleControls
                    Spacer(minLength: 0)
                    subtitleColorControls
                }
                VStack(spacing: 2) {
                    HStack(spacing: 4) {
                        fontScaleControls
                        Spacer(minLength: 0)
                    }
                    HStack(spacing: 4) {
                        Text("Χρώμα")
                            .font(.caption.weight(.semibold))
                        Spacer(minLength: 0)
                        subtitleColorControls
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var fontScaleControls: some View {
        Text("Aa")
            .font(.caption.weight(.bold))
            .frame(minWidth: 22)
            .accessibilityLabel("Μέγεθος όλων των υποτίτλων")
        Button {
            adjustFontScale(by: -0.05)
        } label: {
            Image(systemName: "minus")
                .frame(width: 44, height: 44)
                .background(GSubsTheme.elevated, in: Circle())
        }
        .buttonStyle(.plain)
        .disabled(model.style.fontScale <= 0.75)
        .accessibilityLabel("Μείωση μεγέθους όλων των υποτίτλων")
        .accessibilityIdentifier("font-size-decrease")
        Text("\(Int((model.style.fontScale * 100).rounded()))%")
            .font(.caption.monospacedDigit().weight(.bold))
            .frame(minWidth: 34)
            .accessibilityIdentifier("global-font-value")
        Button {
            adjustFontScale(by: 0.05)
        } label: {
            Image(systemName: "plus")
                .frame(width: 44, height: 44)
                .background(GSubsTheme.elevated, in: Circle())
        }
        .buttonStyle(.plain)
        .disabled(model.style.fontScale >= 1.35)
        .accessibilityLabel("Αύξηση μεγέθους όλων των υποτίτλων")
        .accessibilityIdentifier("font-size-increase")
    }

    @ViewBuilder
    private var subtitleColorControls: some View {
        ForEach(SubtitleColor.allCases) { color in
            Button {
                model.style.foreground = color
            } label: {
                Circle()
                    .fill(color.swatch)
                    .frame(width: 20, height: 20)
                    .overlay {
                        Circle().stroke(
                            model.style.foreground == color ? GSubsTheme.cyan : Color.black.opacity(0.28),
                            lineWidth: model.style.foreground == color ? 3 : 1
                        )
                    }
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Χρώμα όλων: \(color.displayName)")
            .accessibilityIdentifier("subtitle-color-\(color.rawValue)")
        }
    }

    private func mobileLandscapeEditControls(at index: Int) -> some View {
        VStack(spacing: 2) {
            TextField("Υπότιτλος", text: $model.cues[index].text, axis: .vertical)
                .font(.callout.weight(.medium))
                .lineLimit(1, reservesSpace: true)
                .focused($focusedCueID, equals: model.cues[index].id)
                .padding(.horizontal, 8)
                .frame(minHeight: 44)
                .background(GSubsTheme.elevated, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(GSubsTheme.border))
                .accessibilityLabel("Κείμενο υποτίτλου \(index + 1)")
                .accessibilityIdentifier("subtitle-cue-\(index)")
                .simultaneousGesture(TapGesture().onEnded { focusCue(at: index) })
                .id(model.cues[index].id)

            HStack(spacing: 4) {
                Text("Φράση")
                    .font(.caption.weight(.semibold))
                Slider(value: cuePositionBinding(at: index), in: SubtitleStyle.bottomOffsetRange)
                    .tint(GSubsTheme.cyan)
                    .accessibilityLabel("Θέση υποτίτλου \(index + 1)")
                    .accessibilityHint("Αλλάζει μόνο τη θέση αυτής της φράσης.")
                    .accessibilityIdentifier("cue-position-slider-\(index)")
                cuePositionModeButton(at: index)
                if model.cues[index].bottomOffsetOverride != nil {
                    Button {
                        model.cues[index].bottomOffsetOverride = nil
                    } label: {
                        Image(systemName: "arrow.uturn.backward")
                            .frame(width: 44, height: 44)
                            .background(GSubsTheme.cyan.opacity(0.10), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Επαναφορά υποτίτλου \(index + 1) στην κοινή θέση")
                    .accessibilityIdentifier("cue-position-reset-\(index)")
                }
            }
            .frame(minHeight: 44)
            .dynamicTypeSize(...DynamicTypeSize.large)

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 2) {
                    fontScaleControls
                    subtitleColorControls
                    compactGlobalPositionControl
                }
                VStack(spacing: 2) {
                    HStack(spacing: 2) {
                        fontScaleControls
                        Spacer(minLength: 0)
                        subtitleColorControls
                    }
                    compactGlobalPositionControl
                }
            }
            .dynamicTypeSize(...DynamicTypeSize.large)
        }
        .padding(4)
        .background(GSubsTheme.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(GSubsTheme.border))
    }

    private var compactGlobalPositionControl: some View {
        HStack(spacing: 4) {
            Image(systemName: "arrow.up.and.down")
                .font(.caption.weight(.bold))
                .accessibilityHidden(true)
            Slider(value: $model.style.bottomOffset, in: SubtitleStyle.bottomOffsetRange)
                .frame(minWidth: 78)
                .tint(GSubsTheme.cyan)
                .accessibilityLabel("Θέση όλων των υποτίτλων")
                .accessibilityIdentifier("global-position-slider")
        }
        .frame(minHeight: 44)
    }

    private func cuePositionModeButton(at index: Int) -> some View {
        let hasOverride = model.cues[index].bottomOffsetOverride != nil
        return Button {
            if hasOverride {
                model.cues[index].bottomOffsetOverride = nil
            } else {
                model.cues[index].bottomOffsetOverride = model.style.bottomOffset
            }
        } label: {
            Text(hasOverride ? "Δική" : "Κοινή")
                .font(.caption2.weight(.bold))
                .lineLimit(1)
                .frame(minWidth: 52, minHeight: 44)
                .foregroundStyle(hasOverride ? GSubsTheme.cyan : .secondary)
                .background(GSubsTheme.elevated, in: Capsule())
                .overlay(Capsule().stroke(hasOverride ? GSubsTheme.cyan.opacity(0.55) : GSubsTheme.border))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(
            "Θέση υποτίτλου \(index + 1): \(hasOverride ? "δική του" : "κοινή")"
        )
        .accessibilityHint(
            hasOverride
                ? "Επαναφέρει αυτή τη φράση στην κοινή θέση."
                : "Δίνει ξεχωριστή θέση μόνο σε αυτή τη φράση."
        )
        .accessibilityValue(cuePositionAccessibilityValue(at: index))
        .accessibilityIdentifier("cue-position-toggle-\(index)")
    }

    private func cuePositionBinding(at index: Int) -> Binding<Double> {
        Binding(
            get: {
                guard model.cues.indices.contains(index) else { return model.style.bottomOffset }
                return model.style.resolvedBottomOffset(for: model.cues[index])
            },
            set: { newValue in
                guard model.cues.indices.contains(index) else { return }
                model.cues[index].bottomOffsetOverride = newValue
            }
        )
    }

    private func cuePositionAccessibilityValue(at index: Int) -> String {
        let cue = model.cues[index]
        let mode = cue.bottomOffsetOverride == nil ? "Κοινή θέση" : "Δική του θέση"
        let offset = model.style.resolvedBottomOffset(for: cue)
        return "\(mode), \(Int((offset * 100).rounded()))%"
    }

    private var mobileExportResult: some View {
        VStack(spacing: 9) {
            HStack(spacing: 9) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.title2)
                    .foregroundStyle(GSubsTheme.mint)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Έτοιμο")
                        .font(.headline)
                    Text("Το MP4 είναι στο iPhone.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            if let url = model.exportedURL {
                HStack(spacing: 8) {
                    Button {
                        Task { await model.saveExportToPhotos() }
                    } label: {
                        Label(
                            model.isSavingExport ? "Αποθήκευση…" : "Αποθήκευση",
                            systemImage: "photo.badge.plus"
                        )
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .foregroundStyle(.white)
                        .background(GSubsTheme.cyan, in: RoundedRectangle(cornerRadius: 13))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("save-to-photos")
                    .disabled(model.isSavingExport)
                    ShareLink(item: url) {
                        Label("Κοινοποίηση", systemImage: "square.and.arrow.up")
                            .font(.subheadline.weight(.semibold))
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(GSubsTheme.elevated, in: RoundedRectangle(cornerRadius: 13))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("share-export")
                }
            }
            if let error = model.errorMessage {
                compactStatus(error, icon: "exclamationmark.triangle.fill", tint: GSubsTheme.danger)
            } else if let notice = model.noticeMessage {
                compactStatus(notice, icon: "checkmark.circle.fill", tint: GSubsTheme.mint)
            }
        }
        .dynamicTypeSize(...DynamicTypeSize.large)
        .padding(12)
        .background(GSubsTheme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(GSubsTheme.border))
    }

    var selectedCueIndex: Int {
        guard !model.cues.isEmpty else { return 0 }
        guard let selectedCueID,
            let index = model.cues.firstIndex(where: { $0.id == selectedCueID })
        else {
            return 0
        }
        return index
    }

    private var selectedCueIDForPreview: UUID? {
        guard model.cues.indices.contains(selectedCueIndex) else { return nil }
        return model.cues[selectedCueIndex].id
    }

    private func selectPreviousCue() {
        selectCue(at: selectedCueIndex - 1)
    }

    private func selectNextCue() {
        selectCue(at: selectedCueIndex + 1)
    }

    func focusPreviousCue() {
        focusCue(at: selectedCueIndex - 1)
    }

    func focusNextCue() {
        focusCue(at: selectedCueIndex + 1)
    }

    private func selectCue(at index: Int) {
        guard model.cues.indices.contains(index) else { return }
        focusedCueID = nil
        selectedCueID = model.cues[index].id
    }

    private func focusCue(at index: Int) {
        guard model.cues.indices.contains(index) else { return }
        let cueID = model.cues[index].id
        selectedCueID = cueID
        focusedCueID = cueID
    }

    private func adjustFontScale(by change: Double) {
        model.style.fontScale = min(1.35, max(0.75, model.style.fontScale + change))
    }

    private func mobilePreviewHeight(
        availableHeight: CGFloat,
        keyboardIsVisible: Bool
    ) -> CGFloat {
        if keyboardIsVisible {
            let maximum = dynamicTypeSize.isAccessibilitySize ? 56.0 : 72.0
            let reserved = dynamicTypeSize.isAccessibilitySize ? 245.0 : 200.0
            return max(44, min(maximum, availableHeight - reserved))
        }
        let maximum = dynamicTypeSize.isAccessibilitySize ? 145.0 : 290.0
        let minimum = dynamicTypeSize.isAccessibilitySize ? 68.0 : 120.0
        let reserved = dynamicTypeSize.isAccessibilitySize ? 420.0 : 330.0
        return max(minimum, min(maximum, availableHeight - reserved))
    }

    private func positionLabel(for offset: Double) -> String {
        switch offset {
        case ..<0.20: return "Χαμηλά"
        case ..<0.48: return "Κέντρο"
        default: return "Ψηλά"
        }
    }

    private func time(_ seconds: Double) -> String {
        String(
            format: "%d:%02d.%01d",
            Int(seconds) / 60,
            Int(seconds) % 60,
            Int(seconds * 10) % 10
        )
    }
}

extension SubtitleColor {
    fileprivate var displayName: String {
        switch self {
        case .yellow: "Κίτρινο"
        case .white: "Λευκό"
        case .cyan: "Cyan"
        }
    }

    fileprivate var swatch: Color {
        switch self {
        case .yellow: .yellow
        case .white: .white
        case .cyan: GSubsTheme.cyan
        }
    }
}
