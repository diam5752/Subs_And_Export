import React from 'react';

export default function TermsOfService() {
    return (
        <div className="container mx-auto p-8 max-w-4xl">
            <h1 className="text-3xl font-bold mb-6">Terms of Service</h1>
            <div className="prose dark:prose-invert">
                <p className="mb-4">Effective Date: October 24, 2024</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">1. Acceptance of Terms</h2>
                <p>By using Ascentia Subs, you agree to these Terms of Service. If you do not agree, please do not use our service.</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">2. Description of Service</h2>
                <p>Ascentia Subs provides AI-powered video transcription and subtitling services. We reserve the right to modify or discontinue the service at any time.</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">3. User Responsibilities</h2>
                <p>You are responsible for the content you upload. You must not upload illegal, offensive, or copyrighted material you do not have permission to use.</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">4. Intellectual Property</h2>
                <p>You retain ownership of your uploaded content. We claim no ownership over your videos or transcripts.</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">5. Limitation of Liability</h2>
                <p>The service is provided &quot;as is&quot; without warranties of any kind. We are not liable for any damages arising from your use of the service.</p>

                <h2 className="text-2xl font-semibold mt-6 mb-4">6. Governing Law</h2>
                <p>These terms are governed by the laws of the jurisdiction in which we operate.</p>
            </div>
        </div>
    );
}
