import SwiftUI

enum GSubsTheme {
    static let canvas = Color(red: 0.969, green: 0.969, blue: 0.961)
    static let surface = Color.white
    static let elevated = Color(red: 0.941, green: 0.945, blue: 0.953)
    static let cyan = Color(red: 0.071, green: 0.404, blue: 0.957)
    static let blue = Color(red: 0.086, green: 0.376, blue: 0.584)
    static let mint = Color(red: 0.118, green: 0.510, blue: 0.318)
    static let amber = Color(red: 0.776, green: 0.416, blue: 0.129)
    static let danger = Color(red: 0.812, green: 0.200, blue: 0.294)
    static let border = Color(red: 0.871, green: 0.875, blue: 0.890)

    static let brandGradient = LinearGradient(
        colors: [cyan, cyan],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}

struct MidnightBackground: View {
    var body: some View {
        GSubsTheme.canvas
            .ignoresSafeArea()
    }
}

struct BrandMark: View {
    var compact = false

    var body: some View {
        Image("GSubsMark")
            .resizable()
            .scaledToFit()
            .frame(width: compact ? 42 : 58, height: compact ? 42 : 58)
            .accessibilityHidden(true)
    }
}

struct GSubsBrandLogo: View {
    var width: CGFloat = 72
    var showsBeta = true

    var body: some View {
        VStack(spacing: 0) {
            Image("GSubsLogo")
                .resizable()
                .scaledToFit()
                .frame(width: width, height: width * 208 / 280)
            if showsBeta {
                Text("BETA")
                    .font(.system(size: 8, weight: .bold))
                    .tracking(1.4)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 7)
                    .frame(height: 15)
                    .background(GSubsTheme.surface, in: Capsule())
                    .overlay(Capsule().stroke(GSubsTheme.border))
                    .offset(y: -2)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("gsubs beta")
    }
}

struct PrivacyBadge: View {
    @Binding var showsDetails: Bool
    var compact = false

    var body: some View {
        Button {
            showsDetails = true
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.shield.fill")
                    .foregroundStyle(GSubsTheme.blue)
                Text("Το βίντεο μένει στη συσκευή")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                if !compact {
                    Spacer(minLength: 4)
                }
                Image(systemName: "info.circle")
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(minHeight: 44)
            .background(GSubsTheme.surface, in: Capsule())
            .overlay(Capsule().stroke(GSubsTheme.border))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("privacy-details")
        .accessibilityHint("Εμφανίζει πώς χρησιμοποιούνται το βίντεο και ο ήχος.")
    }
}

struct PrivacyDetailsView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    ZStack {
                        Circle()
                            .fill(GSubsTheme.mint.opacity(0.12))
                            .frame(width: 86, height: 86)
                        Image(systemName: "lock.iphone")
                            .font(.system(size: 38, weight: .medium))
                            .foregroundStyle(GSubsTheme.mint)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Το βίντεό σου μένει εδώ.")
                            .font(.system(size: 30, weight: .bold))
                        Text("Η προεπισκόπηση, οι διορθώσεις και το τελικό MP4 γίνονται στο iPhone.")
                            .font(.body)
                            .foregroundStyle(.secondary)
                    }
                    privacyRow(
                        icon: "waveform",
                        title: "Στέλνεται μόνο ήχος",
                        detail: "Για τη μεταγραφή αποστέλλεται προσωρινά συμπιεσμένος ήχος AAC, ποτέ το βίντεο."
                    )
                    privacyRow(
                        icon: "captions.bubble",
                        title: "Επιστρέφουν μόνο υπότιτλοι",
                        detail:
                            "Το gsubs API επιστρέφει το κείμενο και τους χρόνους. Το edit και το export μένουν στη συσκευή."
                    )
                    privacyRow(
                        icon: "clock.arrow.circlepath",
                        title: "Περιορισμένη διατήρηση",
                        detail:
                            "Το αποτέλεσμα στο GSUBS κρατιέται έως 24 ώρες για ασφαλή επανάληψη και αντίγραφά του μπορεί να παραμένουν έως 14 ημέρες στα κρυπτογραφημένα backup του GSUBS. Η πλήρης πολιτική εξηγεί χωριστά τον πάροχο μεταγραφής."
                    )
                    Link(destination: URL(string: "https://gsubs.gr/privacy")!) {
                        Label("Πλήρης Πολιτική Απορρήτου", systemImage: "arrow.up.right.square")
                            .font(.headline)
                            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                    }
                    .accessibilityIdentifier("privacy-policy-link")
                }
                .padding(24)
            }
            .background(MidnightBackground())
            .navigationTitle("Απόρρητο")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Τέλος") { dismiss() }
                        .fontWeight(.semibold)
                }
            }
        }
        .preferredColorScheme(.light)
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    private func privacyRow(icon: String, title: String, detail: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(GSubsTheme.cyan)
                .frame(width: 42, height: 42)
                .background(GSubsTheme.cyan.opacity(0.10), in: RoundedRectangle(cornerRadius: 13))
            VStack(alignment: .leading, spacing: 5) {
                Text(title)
                    .font(.headline)
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

struct CreditsPill: View {
    let balance: Int

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "sparkles")
                .foregroundStyle(GSubsTheme.cyan)
            Text("\(balance) credits")
                .font(.caption.monospacedDigit().weight(.bold))
                .lineLimit(1)
        }
        .padding(.horizontal, 12)
        .frame(height: 38)
        .fixedSize(horizontal: true, vertical: false)
        .background(GSubsTheme.elevated, in: Capsule())
        .overlay(Capsule().stroke(GSubsTheme.border))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(balance) διαθέσιμα πληρωμένα credits")
    }
}

struct StepRail: View {
    let activeStep: Int

    private let steps = [
        ("play.rectangle.fill", "Βίντεο"),
        ("captions.bubble.fill", "Υπότιτλοι"),
        ("square.and.arrow.down.fill", "Export"),
    ]

    var body: some View {
        HStack(spacing: 8) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                if index > 0 {
                    Capsule()
                        .fill(index <= activeStep ? GSubsTheme.cyan.opacity(0.65) : Color.white.opacity(0.10))
                        .frame(height: 2)
                }
                VStack(spacing: 6) {
                    ZStack {
                        Circle()
                            .fill(index <= activeStep ? GSubsTheme.cyan.opacity(0.15) : Color.white.opacity(0.05))
                        Image(systemName: step.0)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(index <= activeStep ? GSubsTheme.cyan : .secondary)
                    }
                    .frame(width: 32, height: 32)
                    Text(step.1)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(index <= activeStep ? .primary : .secondary)
                }
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .background(GSubsTheme.surface.opacity(0.92), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(GSubsTheme.border))
    }
}

struct PrimaryActionButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 56)
            .padding(.horizontal, 18)
            .background(GSubsTheme.brandGradient, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(Color.white.opacity(0.20))
            }
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .opacity(configuration.isPressed ? 0.9 : 1)
            .animation(.easeOut(duration: 0.16), value: configuration.isPressed)
    }
}

extension View {
    func studioCard(cornerRadius: CGFloat = 24) -> some View {
        padding(18)
            .background(GSubsTheme.surface, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).stroke(GSubsTheme.border))
    }
}
