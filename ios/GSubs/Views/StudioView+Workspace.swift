import SwiftUI

extension StudioView {
    @ViewBuilder
    func videoWorkspace(videoURL: URL) -> some View {
        VStack(spacing: 24) {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("Βίντεο")
                        .font(.title3.weight(.bold))
                    Spacer()
                    closeVideoButton
                }
                VideoPreview(
                    videoURL: model.previewURL ?? videoURL,
                    cues: model.cues,
                    style: model.style
                )
                .id(videoURL)
                metadataRow
                if [.extractingAudio, .transcribing].contains(model.phase) {
                    transcriptionProgress
                }
            }
            .studioCard(cornerRadius: 28)

        }
    }

    private var metadataRow: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                metadataChips
            }
            VStack(alignment: .leading, spacing: 8) {
                metadataChips
            }
        }
    }

    @ViewBuilder
    private var metadataChips: some View {
        metadataChip(icon: "clock", text: durationText)
        metadataChip(icon: "sparkles", text: "30 credits")
        metadataChip(icon: "iphone", text: "Στη συσκευή", tint: GSubsTheme.mint)
    }

    private var transcriptionProgress: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                ProgressView()
                    .tint(GSubsTheme.cyan)
                Text(model.phase == .extractingAudio ? "Προετοιμασία ήχου" : "Δημιουργία υποτίτλων")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Image(systemName: "checkmark.shield.fill")
                    .foregroundStyle(GSubsTheme.mint)
            }
            ProgressView(value: model.phase == .extractingAudio ? 0.38 : 0.76)
                .tint(GSubsTheme.cyan)
            Text("Το βίντεο παραμένει στο iPhone.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(14)
        .background(GSubsTheme.elevated, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    @ViewBuilder
    var stickyAction: some View {
        if model.exportedURL == nil {
            VStack(spacing: 0) {
                if !model.cues.isEmpty {
                    if let error = model.errorMessage {
                        compactStatus(
                            error,
                            icon: "exclamationmark.triangle.fill",
                            tint: GSubsTheme.danger
                        )
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel(error)
                        .accessibilityIdentifier("editor-status")
                        .padding(.horizontal, 20)
                        .padding(.top, 8)
                    }
                }
                Divider().overlay(GSubsTheme.border)
                Button {
                    if model.cues.isEmpty {
                        model.generateSubtitles()
                    } else {
                        model.exportVideo()
                    }
                } label: {
                    HStack(spacing: 10) {
                        if model.isProjectOperationInFlight {
                            ProgressView()
                                .tint(GSubsTheme.canvas)
                        } else {
                            Image(
                                systemName: model.cues.isEmpty ? "captions.bubble.fill" : "square.and.arrow.down.fill")
                        }
                        Text(stickyButtonTitle)
                            .frame(maxWidth: .infinity)
                        if !model.isProjectOperationInFlight {
                            Image(systemName: "arrow.right")
                        }
                    }
                }
                .buttonStyle(PrimaryActionButtonStyle())
                .accessibilityIdentifier("primary-action")
                .disabled(model.isProjectOperationInFlight)
                .opacity(model.isProjectOperationInFlight ? 0.72 : 1)
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 8)
            }
            .dynamicTypeSize(...DynamicTypeSize.large)
            .background(GSubsTheme.surface)
        }
    }

    @ViewBuilder var messages: some View {
        if let notice = model.noticeMessage {
            messageCard(notice, icon: "checkmark.circle.fill", tint: GSubsTheme.mint)
        }
        if let error = model.errorMessage {
            messageCard(error, icon: "exclamationmark.triangle.fill", tint: GSubsTheme.danger)
        }
    }

    private var stickyButtonTitle: String {
        if model.phase == .extractingAudio { return "Προετοιμασία ήχου…" }
        if model.phase == .transcribing { return "Δημιουργία υποτίτλων…" }
        if model.phase == .exporting { return "Δημιουργία MP4…" }
        return model.cues.isEmpty ? "Υπότιτλοι · 30 credits" : "Εξαγωγή MP4"
    }

    private var durationText: String {
        let seconds = Int(model.videoDuration.rounded())
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }

    private func metadataChip(icon: String, text: String, tint: Color = GSubsTheme.cyan) -> some View {
        HStack(spacing: 5) {
            Image(systemName: icon)
                .foregroundStyle(tint)
            Text(text)
                .lineLimit(1)
        }
        .font(.caption.weight(.semibold))
        .padding(.horizontal, 10)
        .frame(height: 34)
        .background(GSubsTheme.elevated, in: Capsule())
    }

    private func messageCard(_ text: String, icon: String, tint: Color) -> some View {
        Label(text, systemImage: icon)
            .font(.subheadline)
            .foregroundStyle(.primary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .background(tint.opacity(0.10), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(tint.opacity(0.20)))
    }
}
