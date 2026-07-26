import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { LegalPage } from '@/components/LegalPage';
import { I18nProvider } from '@/context/I18nContext';
import el from '@/i18n/el.json';
import en from '@/i18n/en.json';

const renderPage = (kind: 'privacy' | 'terms', locale: 'el' | 'en' = 'el') => render(
    <I18nProvider initialLocale={locale}>
        <LegalPage kind={kind} />
    </I18nProvider>,
);

describe('LegalPage', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('separates temporary media from retained Greek payment and tax records', () => {
        // REGRESSION: the old policy named Groq and promised a blanket 30-day
        // deletion without explaining that legally required financial records
        // follow a separate retention period.
        renderPage('privacy');

        expect(screen.getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-logo-light.svg');
        expect(screen.getByRole('heading', { name: 'Πολιτική Απορρήτου' })).toBeInTheDocument();
        expect(screen.getByText(/χρειάζεται το gsubs/)).toBeInTheDocument();
        expect(screen.getByText(/ElevenLabs Scribe v2/)).toBeInTheDocument();
        expect(screen.getByText(/πωλήσεις paid credits δεν είναι ενεργές τώρα.*Stripe θα επεξεργάζεται.*e-Τιμολόγιο της ΑΑΔΕ/)).toBeInTheDocument();
        expect(screen.getByText(/αρχεία.*εξαγωγές.*24 ώρες.*τελευταία δραστηριότητα/)).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: '3. Πληρωμές και παραστατικά' })).toBeInTheDocument();
        expect(screen.getByText(/δεν προσφέρει αυτή τη στιγμή.*paid credits.*Stripe-hosted Checkout.*όνομα.*email.*διεύθυνση χρέωσης/)).toBeInTheDocument();
        expect(screen.getByText(/δεν θα λαμβάνει ούτε θα αποθηκεύει.*πλήρη αριθμό κάρτας.*CVC/)).toBeInTheDocument();
        expect(screen.getByText(/MARK, θα διατηρούνται μέχρι το τέλος του πέμπτου πλήρους έτους μετά το σχετικό φορολογικό έτος/)).toBeInTheDocument();
        expect(screen.getByText(/απόδειξη πληρωμής της Stripe.*αποδεικτικό πληρωμής, όχι φορολογικό παραστατικό της ΑΑΔΕ/)).toBeInTheDocument();
        expect(screen.getByText(/κρυπτογραφικό hash.*κανονικοποιημένου email.*365 ημέρες.*credits εγγραφής/)).toBeInTheDocument();
        expect(screen.queryByText(/Groq/)).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Όροι Χρήσης' })).toHaveAttribute('href', '/terms');
    });

    it('renders the English privacy payment disclosures', () => {
        renderPage('privacy', 'en');

        expect(screen.getByRole('heading', { name: '3. Payments and receipts' })).toBeInTheDocument();
        expect(screen.getByText(/does not currently offer paid-credit purchases.*Stripe-hosted Checkout.*name.*email address.*billing address/)).toBeInTheDocument();
        expect(screen.getByText(/MARK, would be retained through the end of the fifth full year after the relevant tax year/)).toBeInTheDocument();
        expect(screen.getByText(/Account deletion would not erase records/)).toBeInTheDocument();
        expect(screen.getByText(/Paid-credit sales are not currently active.*Stripe would process payments.*AADE e-Timologio/)).toBeInTheDocument();
        expect(screen.getByText(/cryptographic hash.*normalized email.*365 days.*signup credits/)).toBeInTheDocument();
    });

    it('renders the Greek digital-service withdrawal policy without a content waiver', () => {
        renderPage('terms');

        const inactiveHeading = screen.getByRole('heading', {
            name: 'Οι πωλήσεις paid credits και η υπαναχώρηση δεν είναι ενεργές',
        });
        expect(inactiveHeading).toBeInTheDocument();
        expect(screen.getByText(
            /δεν προσφέρει ούτε πωλεί.*δεν δημοσιεύονται εδώ ως ισχύοντες όροι.*δεν ανακοινώνει διαθεσιμότητα.*οριστικούς όρους πώλησης/,
        )).toBeInTheDocument();
        expect(inactiveHeading.closest('section')).not.toHaveAttribute('id');
        expect(screen.queryByRole('heading', {
            name: '5. Credits, πληρωμές και παραστατικά',
        })).not.toBeInTheDocument();
        expect(screen.queryByRole('heading', {
            name: 'Υπόδειγμα δήλωσης υπαναχώρησης',
        })).not.toBeInTheDocument();
        expect(document.querySelector('#withdrawal')).toBeNull();
    });

    it('renders the localized English refund policy with studio navigation', () => {
        renderPage('terms', 'en');

        expect(screen.getByRole('heading', { name: 'Terms of Service' })).toBeInTheDocument();
        expect(screen.getByText(/does not currently offer or sell.*intentionally not published here as operative terms.*does not announce availability or final sale terms/)).toBeInTheDocument();
        expect(screen.getByText(/AI-generated results/)).toBeInTheDocument();
        expect(screen.queryByText(/prepaid internal units.*downloadable digital content/)).not.toBeInTheDocument();
        expect(screen.queryByRole('heading', {
            name: 'Model withdrawal statement',
        })).not.toBeInTheDocument();
        expect(document.querySelector('#withdrawal')).toBeNull();
        expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/');
        expect(screen.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/privacy');
        expect(screen.getByRole('link', { name: 'gsubs by Ascentia ↗' }))
            .toHaveAttribute('href', 'https://ascentia-gp.com/');
    });

    // REGRESSION: unpublished paid-credit terms were hidden from the page but
    // still shipped to every browser inside the locale JSON bundles.
    it('does not bundle unpublished paid-credit terms in either locale', () => {
        for (const localeMessages of [el, en]) {
            expect(localeMessages).not.toHaveProperty('termsPaymentsTitle');
            expect(localeMessages).not.toHaveProperty('termsPaymentsBody');
            expect(localeMessages).not.toHaveProperty('termsRefundsTitle');
            expect(localeMessages).not.toHaveProperty('termsRefundsBody');
            expect(localeMessages).not.toHaveProperty('termsWithdrawalTitle');
            expect(localeMessages).not.toHaveProperty('termsWithdrawalBody');
        }
    });
});
