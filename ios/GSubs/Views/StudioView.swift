import PhotosUI
import SwiftUI
import UIKit

struct StudioView: View {
    @ObservedObject var model: AppModel
    @Environment(\.dynamicTypeSize) var dynamicTypeSize
    @State private var pickerItem: PhotosPickerItem?
    @State private var loadingPickedVideo = false
    @State private var pickerTask: Task<Void, Never>?
    @State private var showsPrivacy = false
    @State private var confirmsAccountDeletion = false
    @State var selectedCueID: UUID?
    @State var keyboardIsVisible = false
    @FocusState var focusedCueID: UUID?

    var body: some View {
        NavigationStack {
            ZStack {
                MidnightBackground()
                if let videoURL = model.videoURL, !model.cues.isEmpty {
                    mobileSubtitleEditor(videoURL: videoURL)
                } else {
                    ScrollView {
                        LazyVStack(spacing: 24) {
                            studioHeader
                            if let videoURL = model.videoURL {
                                videoWorkspace(videoURL: videoURL)
                            } else {
                                emptyStudio
                            }
                            messages
                        }
                        .padding(.horizontal, 20)
                        .padding(.top, 10)
                        .padding(.bottom, model.videoURL == nil ? 34 : 112)
                    }
                    .scrollDismissesKeyboard(.interactively)
                    .accessibilityIdentifier("studio-scroll")
                }
            }
            .toolbar(.hidden, for: .navigationBar)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Button {
                        focusPreviousCue()
                    } label: {
                        Image(systemName: "chevron.left")
                    }
                    .disabled(model.isProjectOperationInFlight || selectedCueIndex <= 0)
                    .accessibilityLabel("Προηγούμενος υπότιτλος")
                    .accessibilityIdentifier("keyboard-cue-previous")
                    Button {
                        focusNextCue()
                    } label: {
                        Image(systemName: "chevron.right")
                    }
                    .disabled(
                        model.isProjectOperationInFlight
                            || selectedCueIndex >= model.cues.count - 1
                    )
                    .accessibilityLabel("Επόμενος υπότιτλος")
                    .accessibilityIdentifier("keyboard-cue-next")
                    Spacer()
                    Button("Τέλος") {
                        focusedCueID = nil
                        UIApplication.shared.sendAction(
                            #selector(UIResponder.resignFirstResponder),
                            to: nil,
                            from: nil,
                            for: nil
                        )
                    }
                    .accessibilityIdentifier("keyboard-done")
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if model.videoURL != nil, !keyboardIsVisible {
                    stickyAction
                }
            }
            .sheet(isPresented: $showsPrivacy) {
                PrivacyDetailsView()
            }
            .alert("Διαγραφή λογαριασμού;", isPresented: $confirmsAccountDeletion) {
                Button("Ακύρωση", role: .cancel) {}
                Button("Διαγραφή", role: .destructive) {
                    confirmsAccountDeletion = false
                    Task { await model.deleteAccount() }
                }
            } message: {
                Text(
                    "Ο λογαριασμός και τα ενεργά δεδομένα διαγράφονται οριστικά. Τυχόν υποχρεωτικά φορολογικά στοιχεία διατηρούνται όπως ορίζει η Πολιτική Απορρήτου."
                )
            }
            .onChange(of: model.videoURL) { _, _ in
                selectedCueID = nil
                focusedCueID = nil
            }
            .onChange(of: model.cues.map(\.id)) { _, cueIDs in
                guard let selectedCueID, !cueIDs.contains(selectedCueID) else { return }
                self.selectedCueID = cueIDs.first
            }
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardDidShowNotification)) { _ in
                keyboardIsVisible = true
            }
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardDidHideNotification)) { _ in
                keyboardIsVisible = false
            }
        }
    }

    private var studioHeader: some View {
        studioHeader(logoWidth: 68)
    }

    var mobileEditorHeader: some View {
        studioHeader(logoWidth: 46)
            .dynamicTypeSize(...DynamicTypeSize.large)
    }

    private func studioHeader(logoWidth: CGFloat) -> some View {
        HStack(spacing: 12) {
            GSubsBrandLogo(width: logoWidth)
            Spacer(minLength: 8)
            CreditsPill(balance: model.points?.aiSpendableBalance ?? 0)
            accountMenu
        }
    }

    var accountMenu: some View {
        Menu {
            Button {
                showsPrivacy = true
            } label: {
                Label("Απόρρητο", systemImage: "checkmark.shield")
            }
            if model.videoURL != nil {
                Button {
                    model.resetProject()
                } label: {
                    Label("Νέο βίντεο", systemImage: "plus.rectangle.on.rectangle")
                }
                .disabled(model.isProjectOperationInFlight)
            }
            Divider()
            Button(role: .destructive) {
                confirmsAccountDeletion = true
            } label: {
                Label("Διαγραφή λογαριασμού", systemImage: "person.crop.circle.badge.minus")
            }
            .disabled(model.isProjectOperationInFlight || model.isAccountActionInFlight)
            Button(role: .destructive) {
                Task { await model.signOut() }
            } label: {
                Label("Αποσύνδεση", systemImage: "rectangle.portrait.and.arrow.right")
            }
            .disabled(model.isProjectOperationInFlight || model.isAccountActionInFlight)
        } label: {
            Text(profileInitial)
                .font(.subheadline.weight(.bold))
                .dynamicTypeSize(...DynamicTypeSize.large)
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(GSubsTheme.blue.opacity(0.32), in: Circle())
                .overlay(Circle().stroke(GSubsTheme.blue.opacity(0.55)))
        }
        .accessibilityLabel("Μενού λογαριασμού")
        .accessibilityIdentifier("account-menu")
    }

    var closeVideoButton: some View {
        Button {
            model.resetProject()
        } label: {
            Image(systemName: "xmark")
                .font(.subheadline.weight(.bold))
                .frame(width: 44, height: 44)
                .background(GSubsTheme.elevated, in: Circle())
        }
        .buttonStyle(.plain)
        .disabled(model.isProjectOperationInFlight)
        .accessibilityLabel("Κλείσιμο βίντεο")
        .accessibilityIdentifier("close-video")
    }

    private var emptyStudio: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Υπότιτλοι. Χωρίς κόπο.")
                    .font(.system(size: 34, weight: .bold))
                    .tracking(-0.6)
                    .fixedSize(horizontal: false, vertical: true)
                PrivacyBadge(showsDetails: $showsPrivacy, compact: true)
            }
            videoPicker
        }
    }

    private var videoPicker: some View {
        PhotosPicker(selection: $pickerItem, matching: .videos) {
            VStack(spacing: 18) {
                ZStack {
                    Circle()
                        .fill(GSubsTheme.brandGradient.opacity(0.16))
                        .frame(width: 74, height: 74)
                    Circle()
                        .stroke(GSubsTheme.cyan.opacity(0.20), lineWidth: 1)
                        .frame(width: 74, height: 74)
                    if loadingPickedVideo {
                        ProgressView()
                            .tint(GSubsTheme.cyan)
                            .scaleEffect(1.15)
                    } else {
                        Image(systemName: "play.rectangle.on.rectangle.fill")
                            .font(.system(size: 29, weight: .medium))
                            .foregroundStyle(GSubsTheme.cyan)
                    }
                }
                Text("Έως 3 λεπτά")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    Image(systemName: "photo.on.rectangle")
                    Text(loadingPickedVideo ? "Άνοιγμα…" : "Επίλεξε βίντεο")
                    Image(systemName: "arrow.right")
                }
                .font(.headline)
                .foregroundStyle(GSubsTheme.canvas)
                .frame(maxWidth: .infinity, minHeight: 54)
                .background(GSubsTheme.brandGradient, in: RoundedRectangle(cornerRadius: 17, style: .continuous))
            }
            .padding(20)
            .frame(maxWidth: .infinity, minHeight: 244)
            .background {
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .fill(GSubsTheme.surface.opacity(0.95))
            }
            .overlay {
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .stroke(GSubsTheme.brandGradient.opacity(0.58), lineWidth: 1.4)
            }
            .shadow(color: Color.black.opacity(0.05), radius: 20, y: 10)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("video-picker")
        .disabled(loadingPickedVideo || model.isAccountActionInFlight)
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            pickerTask?.cancel()
            loadingPickedVideo = true
            pickerTask = Task {
                defer {
                    loadingPickedVideo = false
                    pickerItem = nil
                }
                if let video = try? await item.loadTransferable(type: PickedVideo.self) {
                    guard !Task.isCancelled else {
                        try? FileManager.default.removeItem(at: video.url)
                        return
                    }
                    await model.accept(video)
                } else if !Task.isCancelled {
                    model.errorMessage = "Δεν ήταν δυνατή η ανάγνωση του βίντεο."
                }
            }
        }
        .onDisappear {
            pickerTask?.cancel()
            pickerTask = nil
        }
    }

    private var profileInitial: String {
        String((model.profile?.name ?? "G").prefix(1)).uppercased()
    }
}
