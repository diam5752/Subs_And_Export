import SwiftUI
import UIKit

struct LoginView: View {
    private enum LoginField: Hashable {
        case name
        case email
        case password
    }

    @ObservedObject var model: AppModel
    @State private var createAccount = false
    @State private var name = ""
    @State private var email = ""
    @State private var password = ""
    @State private var working = false
    @State private var showsPrivacyDetails = false
    @FocusState private var focusedField: LoginField?

    private var submitIsDisabled: Bool {
        working || email.isEmpty || password.count < 12 || (createAccount && name.isEmpty)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                MidnightBackground()

                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        brandHero
                        authenticationCard

                        PrivacyBadge(showsDetails: $showsPrivacyDetails)
                            .frame(maxWidth: .infinity)
                    }
                    .frame(maxWidth: 520)
                    .padding(.horizontal, 20)
                    .padding(.top, 24)
                    .padding(.bottom, 32)
                    .frame(maxWidth: .infinity)
                }
                .scrollDismissesKeyboard(.interactively)
            }
            .toolbar(.hidden, for: .navigationBar)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Τέλος") {
                        focusedField = nil
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
        }
        .preferredColorScheme(.light)
        .sheet(isPresented: $showsPrivacyDetails) {
            PrivacyDetailsView()
        }
    }

    private var brandHero: some View {
        VStack(alignment: .leading, spacing: 22) {
            GSubsBrandLogo(width: 84)
            Text("Υπότιτλοι. Χωρίς κόπο.")
                .font(.system(size: 36, weight: .bold))
                .tracking(-1.1)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var authenticationCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            Picker("Τρόπος πρόσβασης", selection: $createAccount) {
                Text("Σύνδεση").tag(false)
                Text("Εγγραφή").tag(true)
            }
            .pickerStyle(.segmented)
            .accessibilityLabel("Τρόπος πρόσβασης")

            VStack(spacing: 12) {
                if createAccount {
                    nameField
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                emailField
                passwordField
            }
            .animation(.easeInOut(duration: 0.2), value: createAccount)

            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(GSubsTheme.danger)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(
                        GSubsTheme.danger.opacity(0.10), in: RoundedRectangle(cornerRadius: 14, style: .continuous)
                    )
                    .overlay {
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .stroke(GSubsTheme.danger.opacity(0.20))
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("auth-error")
            }

            Button(action: submit) {
                HStack(spacing: 10) {
                    if working {
                        ProgressView()
                            .tint(GSubsTheme.canvas)
                    }
                    Text(createAccount ? "Δημιουργία λογαριασμού" : "Σύνδεση")
                }
            }
            .buttonStyle(PrimaryActionButtonStyle())
            .disabled(submitIsDisabled)
            .opacity(submitIsDisabled ? 0.48 : 1)
            .accessibilityLabel(
                Text(working ? "Η σύνδεση είναι σε εξέλιξη" : (createAccount ? "Δημιουργία λογαριασμού" : "Σύνδεση"))
            )
            .accessibilityIdentifier("auth-submit")

        }
        .studioCard(cornerRadius: 26)
    }

    private var nameField: some View {
        HStack(spacing: 12) {
            fieldIcon("person.fill")
            TextField("Όνομα", text: $name)
                .textContentType(.name)
                .submitLabel(.next)
                .focused($focusedField, equals: .name)
                .onSubmit { focusedField = .email }
                .accessibilityLabel("Όνομα")
        }
        .loginFieldBackground()
    }

    private var emailField: some View {
        HStack(spacing: 12) {
            fieldIcon("envelope.fill")
            TextField("Ηλεκτρονική διεύθυνση", text: $email)
                .textContentType(.emailAddress)
                .textInputAutocapitalization(.never)
                .keyboardType(.emailAddress)
                .submitLabel(.next)
                .focused($focusedField, equals: .email)
                .onSubmit { focusedField = .password }
                .accessibilityLabel("Ηλεκτρονική διεύθυνση")
        }
        .loginFieldBackground()
    }

    private var passwordField: some View {
        HStack(spacing: 12) {
            fieldIcon("lock.fill")
            SecureField("Κωδικός · 12+ χαρακτήρες", text: $password)
                .textContentType(createAccount ? .newPassword : .password)
                .submitLabel(.go)
                .focused($focusedField, equals: .password)
                .onSubmit {
                    guard !submitIsDisabled else { return }
                    submit()
                }
                .accessibilityLabel("Κωδικός")
        }
        .loginFieldBackground()
    }

    private func fieldIcon(_ systemName: String) -> some View {
        Image(systemName: systemName)
            .font(.system(size: 15, weight: .semibold))
            .foregroundStyle(GSubsTheme.cyan)
            .frame(width: 20)
            .accessibilityHidden(true)
    }

    private func submit() {
        working = true
        Task {
            if createAccount {
                await model.register(name: name, email: email, password: password)
            } else {
                await model.signIn(email: email, password: password)
            }
            working = false
        }
    }
}

extension View {
    fileprivate func loginFieldBackground() -> some View {
        frame(minHeight: 56)
            .padding(.horizontal, 16)
            .background(GSubsTheme.elevated, in: RoundedRectangle(cornerRadius: 17, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 17, style: .continuous)
                    .stroke(GSubsTheme.border)
            }
    }
}
