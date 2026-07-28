import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { LegalPage } from '@/components/LegalPage';
import { I18nProvider } from '@/context/I18nContext';
import el from '@/i18n/el.json';
import en from '@/i18n/en.json';

const mockPaidCreditLegalPublication = { approved: false };

jest.mock('@/lib/paidCreditLegal', () => ({
    paidCreditLegalPublicationIsApproved: () => (
        mockPaidCreditLegalPublication.approved
    ),
}));

const renderPage = (kind: 'privacy' | 'terms', locale: 'el' | 'en' = 'el') => render(
    <I18nProvider initialLocale={locale}>
        <LegalPage kind={kind} />
    </I18nProvider>,
);

describe('LegalPage', () => {
    beforeEach(() => {
        localStorage.clear();
        mockPaidCreditLegalPublication.approved = false;
    });

    it('separates temporary media from retained Greek payment and tax records', () => {
        // REGRESSION: the old policy named Groq and promised a blanket 30-day
        // deletion without explaining that legally required financial records
        // follow a separate retention period.
        renderPage('privacy');

        expect(screen.getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-logo.svg');
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

    it('keeps inactive Greek paid-credit terms out of the public page', () => {
        renderPage('terms');

        const inactiveHeading = screen.getByRole('heading', {
            name: 'Προτεινόμενοι όροι paid credits — οι πωλήσεις παραμένουν ανενεργές',
        });
        expect(inactiveHeading).toBeInTheDocument();
        expect(screen.getByText(
            /δεν προσφέρει ούτε πωλεί.*σαφώς ανενεργό κείμενο.*όχι ως ισχύουσα προσφορά.*checkout θα παραμείνει κλειστό/,
        )).toBeInTheDocument();
        expect(inactiveHeading.closest('section')).not.toHaveAttribute('id');
        expect(screen.queryByRole('heading', {
            name: '7. Paid credits, Ελλάδα και πληρωμή',
        })).not.toBeInTheDocument();
        expect(screen.queryByText(
            /μόνο σε καταναλωτές με διεύθυνση χρέωσης στην Ελλάδα.*ΦΠΑ 24%.*επιλέξιμο μέσο πληρωμής.*προεγκρίνεται προσωρινά.*είσπραξη.*ελληνικής διεύθυνσης.*προέγκριση θα ακυρώνεται.*MARK/,
        )).not.toBeInTheDocument();
        expect(screen.queryByText(
            /Δεν θα γίνονται αυτόματες επιστροφές.*δεν περιορίζει κανένα υποχρεωτικό δικαίωμα.*χειροκίνητα στη Stripe.*λογιστής στην ΑΑΔΕ/,
        )).not.toBeInTheDocument();
        expect(screen.queryByText(
            /14 ημέρες.*αναλογικό ποσό.*μόνο μετά την πλήρη εκτέλεση.*νόμιμες προϋποθέσεις/,
        )).not.toBeInTheDocument();
        expect(screen.queryByRole('heading', {
            name: 'Υπόδειγμα δήλωσης υπαναχώρησης',
        })).not.toBeInTheDocument();
        expect(document.querySelector('#withdrawal')).toBeNull();
    });

    it('keeps inactive English paid-credit terms out of the public page', () => {
        renderPage('terms', 'en');

        expect(screen.getByRole('heading', { name: 'Terms of Service' })).toBeInTheDocument();
        expect(screen.getByText(/does not currently offer or sell.*clearly inactive text.*not as an operative offer.*Checkout will remain closed/)).toBeInTheDocument();
        expect(screen.getByText(/AI-generated results/)).toBeInTheDocument();
        expect(screen.queryByText(/only to consumers with a billing address in Greece.*24% VAT.*eligible payment method.*temporarily authorized.*Capture.*Greek billing address.*authorization will be canceled/)).not.toBeInTheDocument();
        expect(screen.queryByText(/no automatic refunds or discretionary refunds.*does not restrict any mandatory consumer right.*manually in Stripe.*manually in AADE/)).not.toBeInTheDocument();
        expect(screen.queryByRole('heading', {
            name: 'Model withdrawal statement',
        })).not.toBeInTheDocument();
        expect(document.querySelector('#withdrawal')).toBeNull();
        expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/');
        expect(screen.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/privacy');
        expect(screen.getByRole('link', { name: 'gsubs by Ascentia ↗' }))
            .toHaveAttribute('href', 'https://ascentia-gp.com/');
    });

    it('renders operative paid-credit terms only for an approved publication', () => {
        mockPaidCreditLegalPublication.approved = true;
        renderPage('terms');

        expect(screen.queryByRole('heading', {
            name: 'Προτεινόμενοι όροι paid credits — οι πωλήσεις παραμένουν ανενεργές',
        })).not.toBeInTheDocument();
        expect(screen.getByRole('heading', {
            name: '7. Paid credits, Ελλάδα και πληρωμή',
        })).toBeInTheDocument();
        expect(screen.getByRole('heading', {
            name: 'Υπόδειγμα δήλωσης υπαναχώρησης',
        })).toBeInTheDocument();
        expect(document.querySelector('#withdrawal')).not.toBeNull();
    });

    it('keeps the inactive notice localized in both locales', () => {
        for (const localeMessages of [el, en]) {
            expect(localeMessages).toHaveProperty('termsPaidCreditsDraftTitle');
            expect(localeMessages).toHaveProperty('termsPaidCreditsDraftBody');
        }
    });
});
