import SwiftUI

struct LoginView: View {
    @ObservedObject var model: AppModel
    @State private var createAccount = false
    @State private var name = ""
    @State private var email = ""
    @State private var password = ""
    @State private var working = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    brand
                    Picker("Τρόπος σύνδεσης", selection: $createAccount) {
                        Text("Σύνδεση").tag(false)
                        Text("Νέος λογαριασμός").tag(true)
                    }
                    .pickerStyle(.segmented)
                    if createAccount {
                        TextField("Όνομα", text: $name)
                            .textContentType(.name)
                    }
                    TextField("Email", text: $email)
                        .textContentType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.emailAddress)
                    SecureField("Κωδικός (τουλάχιστον 12 χαρακτήρες)", text: $password)
                        .textContentType(createAccount ? .newPassword : .password)
                    if let error = model.errorMessage {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote)
                            .foregroundStyle(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    Button(action: submit) {
                        if working {
                            ProgressView()
                        } else {
                            Text(createAccount ? "Δημιουργία λογαριασμού" : "Σύνδεση")
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(working || email.isEmpty || password.count < 12 || (createAccount && name.isEmpty))
                    privacyNote
                }
                .textFieldStyle(.roundedBorder)
                .padding(24)
            }
            .background(Color.black)
        }
    }

    private var brand: some View {
        VStack(spacing: 8) {
            Image(systemName: "captions.bubble.fill")
                .font(.system(size: 54))
                .foregroundStyle(.cyan)
            Text("GSubs")
                .font(.system(size: 38, weight: .black, design: .rounded))
            Text("Υπότιτλοι από το API. Editing στο iPhone.")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.top, 36)
    }

    private var privacyNote: some View {
        Label {
            Text("Το βίντεο δεν ανεβαίνει. Στέλνεται μόνο προσωρινός συμπιεσμένος ήχος· το αποτέλεσμα υποτίτλων κρατιέται έως 24 ώρες για ασφαλή επανάληψη και έως 14 ημέρες μόνο σε κρυπτογραφημένα αντίγραφα ασφαλείας.")
        } icon: {
            Image(systemName: "iphone.gen3.radiowaves.left.and.right")
        }
        .font(.footnote)
        .foregroundStyle(.secondary)
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16))
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
