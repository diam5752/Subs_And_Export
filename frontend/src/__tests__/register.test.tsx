import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import RegisterPage from '@/app/register/page';
import { I18nProvider } from '@/context/I18nContext';
import el from '@/i18n/el.json';
import en from '@/i18n/en.json';

jest.mock('@/context/AuthContext', () => ({
    useAuth: () => ({ register: jest.fn() }),
}));

jest.mock('next/navigation', () => ({
    useRouter: () => ({ push: jest.fn() }),
}));

const renderPage = (locale: 'el' | 'en' = 'el') => render(
    <I18nProvider initialLocale={locale}>
        <RegisterPage />
    </I18nProvider>,
);

describe('RegisterPage', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('uses the canonical gsubs identity', () => {
        renderPage();

        const homeLink = screen.getByRole('link', { name: el.brandHomeLabel });
        expect(within(homeLink).getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-logo.svg');
        expect(screen.getByText('gsubs')).toBeInTheDocument();
        expect(screen.getByText(el.registerTitle)).toBeInTheDocument();
        expect(screen.getByText(el.betaLaunchOfferKicker)).toBeInTheDocument();
        expect(screen.getByText(el.betaLaunchOfferTitle)).toBeInTheDocument();
        expect(screen.getByText(el.betaLaunchOfferBody)).toBeInTheDocument();
    });

    // REGRESSION: legal navigation replaced the registration document and
    // discarded already-entered account details.
    it.each([
        ['el', el],
        ['en', en],
    ] as const)('shows localized legal links before account creation in %s', (locale, copy) => {
        renderPage(locale);

        const notice = document.getElementById('register-legal-notice');
        expect(notice).toBeInTheDocument();
        expect(notice).toHaveTextContent(copy.registerLegalIntro);
        expect(notice).toHaveTextContent(copy.registerLegalConnector);
        const termsLink = within(notice as HTMLElement).getByRole('link', {
            name: copy.registerLegalTermsLink,
        });
        const privacyLink = within(notice as HTMLElement).getByRole('link', {
            name: copy.registerLegalPrivacyLink,
        });
        expect(termsLink).toHaveAttribute('href', '/terms');
        expect(termsLink).toHaveAttribute('target', '_blank');
        expect(termsLink).toHaveAttribute('rel', 'noopener noreferrer');
        expect(privacyLink).toHaveAttribute('href', '/privacy');
        expect(privacyLink).toHaveAttribute('target', '_blank');
        expect(privacyLink).toHaveAttribute('rel', 'noopener noreferrer');

        const submitButton = screen.getByRole('button', { name: copy.registerSubmit });
        expect(submitButton).toHaveAttribute('aria-describedby', 'register-legal-notice');
        expect(notice?.nextElementSibling).toBe(submitButton);
    });
});
