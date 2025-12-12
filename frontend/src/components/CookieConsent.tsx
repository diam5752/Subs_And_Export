
'use client';

import React, { useState, useEffect } from 'react';

export default function CookieConsent() {
    const [visible, setVisible] = useState(false);

    useEffect(() => {
        const consent = localStorage.getItem('cookie-consent');
        if (!consent) {
            setVisible(true);
        }
    }, []);

    const accept = () => {
        localStorage.setItem('cookie-consent', 'accepted');
        setVisible(false);
    };

    if (!visible) return null;

    return (
        <div className="fixed bottom-0 left-0 right-0 bg-gray-900 border-t border-gray-800 p-4 shadow-lg z-50 animate-slide-up">
            <div className="container mx-auto flex flex-col sm:flex-row justify-between items-center gap-4">
                <div className="text-sm text-gray-300">
                    We use cookies to ensure you get the best experience on our website.
                    By continuing to use the site, you agree to our <a href="/privacy" className="underline hover:text-white">Privacy Policy</a>.
                </div>
                <button
                    onClick={accept}
                    className="bg-primary hover:bg-primary/90 text-white px-6 py-2 rounded-md font-medium transition-colors text-sm whitespace-nowrap"
                >
                    Accept & Close
                </button>
            </div>
        </div>
    );
}
