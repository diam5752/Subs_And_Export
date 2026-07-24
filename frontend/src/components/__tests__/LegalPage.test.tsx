import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { LegalPage } from '@/components/LegalPage';
import { I18nProvider } from '@/context/I18nContext';

const renderPage = (kind: 'privacy' | 'terms', locale: 'el' | 'en' = 'el') => render(
    <I18nProvider initialLocale={locale}>
        <LegalPage kind={kind} />
    </I18nProvider>,
);

describe('LegalPage', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('describes the active Scribe v2 provider and the actual upload retention behavior', () => {
        // REGRESSION: the old policy named Groq and promised a blanket 30-day
        // deletion even though the product currently uses Scribe v2 and cleans
        // original uploads after 24 hours.
        renderPage('privacy');

        expect(screen.getByRole('heading', { name: 'Πολιτική Απορρήτου' })).toBeInTheDocument();
        expect(screen.getByText(/ElevenLabs Scribe v2/)).toBeInTheDocument();
        expect(screen.getByText(/αρχεία upload.*24 ώρες/)).toBeInTheDocument();
        expect(screen.queryByText(/Groq/)).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Όροι Χρήσης' })).toHaveAttribute('href', '/terms');
    });

    it('renders a localized English terms page with studio navigation', () => {
        renderPage('terms', 'en');

        expect(screen.getByRole('heading', { name: 'Terms of Service' })).toBeInTheDocument();
        expect(screen.getByText(/AI-generated results/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/');
        expect(screen.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/privacy');
    });
});
