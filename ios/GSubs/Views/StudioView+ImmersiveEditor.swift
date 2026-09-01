import SwiftUI
import UIKit

extension StudioView {
    func immersiveMobileSubtitleEditor(videoURL: URL) -> some View {
        GeometryReader { proxy in
            ZStack(alignment: .top) {
                ImmersiveVideoCanvas(
                    videoURL: model.previewURL ?? videoURL,
                    cues: $model.cues,
                    style: model.style,
                    selectedCueID: $selectedCueID,
                    focusedCueID: focusedCueID,
                    subtitleFocus: $focusedCueID
                )
                .id(videoURL)
                .overlay(alignment: .top) {
                    if !immersiveToolsPresented, !keyboardIsVisible {
                        immersiveToolsHandle(topInset: proxy.safeAreaInsets.top)
                    }
                }

                if immersiveToolsPresented {
                    Color.black.opacity(0.34)
                        .ignoresSafeArea()
                        .contentShape(Rectangle())
                        .onTapGesture(perform: closeImmersiveTools)
                        .accessibilityHidden(true)

                    immersiveToolsDrawer(topInset: proxy.safeAreaInsets.top)
                        .transition(.move(edge: .top).combined(with: .opacity))
                        .zIndex(2)
                }
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
            .background(Color.black)
        }
        .ignoresSafeArea(.container, edges: .all)
        .persistentSystemOverlays(.hidden)
    }

    private func immersiveToolsHandle(topInset: CGFloat) -> some View {
        ZStack(alignment: .top) {
            Color.clear
            ZStack {
                Capsule()
                    .fill(Color.black.opacity(0.42))
                    .frame(width: 58, height: 24)
                VStack(spacing: 2) {
                    Capsule()
                        .fill(Color.white.opacity(0.92))
                        .frame(width: 34, height: 3)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(Color.white.opacity(0.82))
                }
            }
            .frame(width: 72, height: 44)
            .padding(.top, max(2, topInset + 2))
            .allowsHitTesting(false)
        }
        .frame(maxWidth: .infinity)
        .frame(height: max(110, topInset + 82))
        .contentShape(Rectangle())
        .onTapGesture(perform: openImmersiveTools)
        .gesture(openToolsGesture(topInset: topInset))
        .accessibilityElement()
        .accessibilityAddTraits(.isButton)
        .accessibilityAction(.default, openImmersiveTools)
        .accessibilityLabel("Περισσότερα εργαλεία")
        .accessibilityHint("Σύρε προς τα κάτω ή ενεργοποίησε για να εμφανιστούν οι επιλογές.")
        .accessibilityIdentifier("immersive-tools-handle")
    }

    private func immersiveToolsDrawer(topInset: CGFloat) -> some View {
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                closeVideoButton
                Spacer(minLength: 4)
                VStack(spacing: 1) {
                    Text("Εργαλεία")
                        .font(.headline)
                    Text("πάνω στο βίντεο")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 4)
                accountMenu
                Button(action: closeImmersiveTools) {
                    Image(systemName: "chevron.up")
                        .font(.subheadline.weight(.bold))
                        .frame(width: 44, height: 44)
                        .background(GSubsTheme.elevated, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Κλείσιμο εργαλείων")
                .accessibilityHint("Επιστρέφει στο καθαρό βίντεο πλήρους οθόνης.")
                .accessibilityIdentifier("immersive-tools-close")
            }

            Label(
                "Πάτημα για κείμενο · σύρσιμο για θέση της τρέχουσας φράσης",
                systemImage: "hand.draw.fill"
            )
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .lineLimit(2)
            .frame(maxWidth: .infinity, minHeight: 30, alignment: .leading)

            cueNavigation

            globalSizeAndColorControls
                .dynamicTypeSize(...DynamicTypeSize.large)

            if model.exportedURL != nil {
                mobileExportResult
            } else {
                immersiveExportRow
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, max(8, topInset + 8))
        .padding(.bottom, 12)
        .frame(maxWidth: .infinity)
        .background(.ultraThinMaterial)
        .background(GSubsTheme.surface.opacity(0.92))
        .clipShape(
            UnevenRoundedRectangle(
                bottomLeadingRadius: 28,
                bottomTrailingRadius: 28,
                style: .continuous
            )
        )
        .overlay(alignment: .bottom) {
            Capsule()
                .fill(Color.secondary.opacity(0.42))
                .frame(width: 44, height: 4)
                .padding(.bottom, 5)
        }
        .shadow(color: .black.opacity(0.30), radius: 24, y: 12)
        .gesture(closeToolsGesture)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("immersive-tools-drawer")
    }

    private var immersiveExportRow: some View {
        VStack(spacing: 6) {
            if let error = model.errorMessage {
                compactStatus(
                    error,
                    icon: "exclamationmark.triangle.fill",
                    tint: GSubsTheme.danger
                )
                .accessibilityElement(children: .combine)
                .accessibilityLabel(error)
                .accessibilityIdentifier("editor-status")
            } else if let notice = model.noticeMessage {
                compactStatus(notice, icon: "checkmark.circle.fill", tint: GSubsTheme.mint)
            }

            HStack(spacing: 8) {
                if model.cues.indices.contains(selectedCueIndex),
                    model.cues[selectedCueIndex].bottomOffsetOverride != nil
                {
                    Button {
                        model.cues[selectedCueIndex].bottomOffsetOverride = nil
                    } label: {
                        Label("Επαναφορά θέσης", systemImage: "arrow.uturn.backward")
                            .font(.caption.weight(.semibold))
                            .lineLimit(1)
                            .frame(minHeight: 48)
                            .padding(.horizontal, 10)
                            .background(GSubsTheme.elevated, in: RoundedRectangle(cornerRadius: 14))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Επαναφορά τρέχουσας φράσης στην κοινή θέση")
                    .accessibilityIdentifier("current-cue-position-reset")
                }

                Button {
                    model.exportVideo()
                } label: {
                    HStack(spacing: 8) {
                        if model.isProjectOperationInFlight {
                            ProgressView()
                                .tint(GSubsTheme.canvas)
                        } else {
                            Image(systemName: "square.and.arrow.down.fill")
                        }
                        Text(model.phase == .exporting ? "Δημιουργία MP4…" : "Εξαγωγή MP4")
                            .frame(maxWidth: .infinity)
                        if !model.isProjectOperationInFlight {
                            Image(systemName: "arrow.right")
                        }
                    }
                    .font(.headline)
                    .foregroundStyle(GSubsTheme.canvas)
                    .padding(.horizontal, 14)
                    .frame(maxWidth: .infinity, minHeight: 50)
                    .background(GSubsTheme.brandGradient, in: RoundedRectangle(cornerRadius: 15))
                }
                .buttonStyle(.plain)
                .disabled(model.isProjectOperationInFlight)
                .accessibilityIdentifier("primary-action")
            }
        }
    }

    private func openToolsGesture(topInset: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 24, coordinateSpace: .local)
            .onEnded { value in
                guard !immersiveToolsPresented,
                    value.startLocation.y <= max(110, topInset + 82),
                    value.translation.height > 54,
                    abs(value.translation.height) > abs(value.translation.width)
                else {
                    return
                }
                openImmersiveTools()
            }
    }

    private var closeToolsGesture: some Gesture {
        DragGesture(minimumDistance: 20, coordinateSpace: .local)
            .onEnded { value in
                guard value.translation.height < -42,
                    abs(value.translation.height) > abs(value.translation.width)
                else {
                    return
                }
                closeImmersiveTools()
            }
    }

    private func openImmersiveTools() {
        focusedCueID = nil
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
        withAnimation(.spring(response: 0.34, dampingFraction: 0.86)) {
            immersiveToolsPresented = true
        }
    }

    private func closeImmersiveTools() {
        withAnimation(.spring(response: 0.30, dampingFraction: 0.90)) {
            immersiveToolsPresented = false
        }
    }

}
