import PhotosUI
import SwiftUI

struct StudioView: View {
    @ObservedObject var model: AppModel
    @State private var pickerItem: PhotosPickerItem?
    @State private var loadingPickedVideo = false
    @State private var pickerTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 18) {
                    privacyCard
                    accountCard
                    if let videoURL = model.videoURL {
                        VideoPreview(videoURL: videoURL, cues: model.cues, style: model.style)
                            .id(videoURL)
                        selectedVideoActions
                        if !model.cues.isEmpty {
                            styleControls
                            cueEditor
                            exportActions
                        }
                    } else {
                        videoPicker
                    }
                    messages
                }
                .padding()
            }
            .navigationTitle("GSubs iOS")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if model.videoURL != nil {
                        Button("Νέο") { model.resetProject() }
                            .disabled(model.isProjectOperationInFlight)
                            .accessibilityHint("Καθαρίζει το τρέχον τοπικό project.")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Έξοδος") { Task { await model.signOut() } }
                        .disabled(model.isProjectOperationInFlight)
                        .accessibilityHint("Αποσυνδέει τον λογαριασμό από τη συσκευή.")
                }
            }
            .background(Color.black)
        }
    }

    private var privacyCard: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "lock.iphone")
                .font(.title2)
                .foregroundStyle(.green)
            VStack(alignment: .leading, spacing: 4) {
                Text("Local video processing")
                    .font(.headline)
                Text("Το αρχικό και το τελικό βίντεο δεν πηγαίνουν ποτέ στον server. Η προεπισκόπηση, η διόρθωση και το MP4 γίνονται στο iPhone.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Text("Μόνο προσωρινός ήχος AAC στέλνεται για Scribe v2. Το αποτέλεσμα υποτίτλων μένει έως 24 ώρες για ασφαλή επανάληψη και έως 14 ημέρες μόνο σε κρυπτογραφημένα αντίγραφα ασφαλείας.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
    }

    private var accountCard: some View {
        HStack {
            VStack(alignment: .leading) {
                Text(model.profile?.name ?? "GSubs")
                    .font(.headline)
                Text("Διαθέσιμα credits")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text("\(model.points?.balance ?? 0)")
                .font(.title2.bold())
                .foregroundStyle(.cyan)
        }
        .padding(.horizontal, 4)
    }

    private var videoPicker: some View {
        PhotosPicker(selection: $pickerItem, matching: .videos) {
            VStack(spacing: 16) {
                if loadingPickedVideo {
                    ProgressView()
                } else {
                    Image(systemName: "photo.on.rectangle.angled")
                        .font(.system(size: 46))
                        .foregroundStyle(.cyan)
                    Text("Διάλεξε βίντεο από το iPhone")
                        .font(.headline)
                    Text("Έως 3 λεπτά · δεν ανεβαίνει στον server")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, minHeight: 240)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 24))
        }
        .disabled(loadingPickedVideo)
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            pickerTask?.cancel()
            loadingPickedVideo = true
            pickerTask = Task {
                defer { loadingPickedVideo = false; pickerItem = nil }
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

    private var selectedVideoActions: some View {
        VStack(spacing: 10) {
            HStack {
                Label(durationText, systemImage: "clock")
                Spacer()
                Text("30 credits")
                    .font(.subheadline.bold())
            }
            Button {
                model.generateSubtitles()
            } label: {
                phaseLabel(
                    busy: [.extractingAudio, .transcribing].contains(model.phase),
                    text: model.cues.isEmpty ? "Δημιουργία υποτίτλων" : "Νέα μεταγραφή"
                )
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled([.extractingAudio, .transcribing, .exporting].contains(model.phase))
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
    }

    private var styleControls: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Εμφάνιση").font(.headline)
            HStack {
                Text("Μέγεθος")
                Slider(value: $model.style.fontScale, in: 0.75...1.35)
            }
            HStack {
                Text("Ύψος")
                Slider(value: $model.style.bottomOffset, in: 0.06...0.72)
            }
            Picker("Χρώμα", selection: $model.style.foreground) {
                ForEach(SubtitleColor.allCases) { color in
                    Text(color.rawValue.capitalized).tag(color)
                }
            }
            .pickerStyle(.segmented)
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
    }

    private var cueEditor: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Διόρθωση υποτίτλων").font(.headline)
            ForEach($model.cues) { $cue in
                VStack(alignment: .leading, spacing: 6) {
                    Text("\(time(cue.start)) – \(time(cue.end))")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                    TextField("Υπότιτλος", text: $cue.text, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(1...3)
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
    }

    private var exportActions: some View {
        VStack(spacing: 10) {
            Button {
                model.exportVideo()
            } label: {
                phaseLabel(busy: model.phase == .exporting, text: "Export MP4 στο iPhone")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled([.extractingAudio, .transcribing, .exporting].contains(model.phase))
            if let url = model.exportedURL {
                HStack {
                    ShareLink(item: url) {
                        Label("Κοινοποίηση", systemImage: "square.and.arrow.up")
                    }
                    Spacer()
                    Button {
                        Task { await model.saveExportToPhotos() }
                    } label: {
                        Label("Φωτογραφίες", systemImage: "photo.badge.plus")
                    }
                }
                .buttonStyle(.bordered)
            }
        }
    }

    @ViewBuilder private var messages: some View {
        if let notice = model.noticeMessage {
            Label(notice, systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        if let error = model.errorMessage {
            Label(error, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var durationText: String {
        let seconds = Int(model.videoDuration.rounded())
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }

    private func time(_ seconds: Double) -> String {
        String(format: "%d:%02d.%01d", Int(seconds) / 60, Int(seconds) % 60, Int(seconds * 10) % 10)
    }

    private func phaseLabel(busy: Bool, text: String) -> some View {
        HStack {
            if busy { ProgressView() }
            Text(text).frame(maxWidth: .infinity)
        }
    }
}
