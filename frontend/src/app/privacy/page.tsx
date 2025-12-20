
import React from 'react';
import Link from 'next/link';

export default function PrivacyPolicy() {
    return (
        <div className="container mx-auto p-8 max-w-4xl">
            <h1 className="text-3xl font-bold mb-6">Privacy Policy</h1>
            <div className="prose dark:prose-invert">
                <p className="mb-4">Effective Date: {new Date().toLocaleDateString()}</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">1. Data Collection</h2>
                <p>We collect uploaded videos and generated subtitles for the purpose of providing the service. We also store minimal user profile information (email, name) for account management.</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">2. Data Retention</h2>
                <p>Uploaded files and generated artifacts are automatically deleted after 30 days. You may manually delete your data at any time via your dashboard.</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">3. Data Sharing</h2>
                <p>We do not share your personal data with third parties, except as required to provide the service (e.g., sending audio to Groq for transcription and transcript text to OpenAI for fact checking or social copy when enabled). These providers are bound by data processing agreements.</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">4. Your Rights</h2>
                <p>Under GDPR, you have the right to access, rectify, and erase your data. Use the &quot;Export Data&quot; and &quot;Delete Account&quot; features in your profile settings to exercise these rights.</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">5. Contact</h2>
                <p>For privacy inquiries, please contact support.</p>

                <p className="mt-8 pt-8 border-t border-[var(--border)]">
                    Please also review our <Link href="/terms" className="text-[var(--accent)] hover:underline">Terms of Service</Link>.
                </p>
            </div>
        </div>
    );
}
