import React, { useState } from 'react';
import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
} from '@testing-library/react';
import '@testing-library/jest-dom';
import {
    CreditPurchaseDialog,
    isAllowedStripeCheckoutUrl,
} from '@/components/CreditPurchaseDialog';
import { api, type CreditCatalogResponse } from '@/lib/api';

const mockPaidCreditLegalPublication = { approved: true };
const mockLocaleState = { locale: 'el' as 'el' | 'en' };

jest.mock('@/lib/paidCreditLegal', () => ({
    paidCreditLegalPublicationIsApproved: () => (
        mockPaidCreditLegalPublication.approved
    ),
}));

jest.mock('@/lib/api', () => ({
    api: {
        getCreditCatalog: jest.fn(),
        createCreditCheckout: jest.fn(),
    },
}));

jest.mock('@/context/I18nContext', () => {
    const translate = (key: string, values?: Record<string, string | number>) => (
        values ? `${key}:${JSON.stringify(values)}` : key
    );
    return {
        useI18n: () => ({ locale: mockLocaleState.locale, t: translate }),
    };
});

jest.mock('@/context/PointsContext', () => ({
    usePoints: () => ({
        balance: 35,
        paidBalance: 20,
        promotionalBalance: 15,
        reversalDebt: 0,
        aiSpendableBalance: 20,
        isLoading: false,
        error: null,
        refreshBalance: jest.fn(),
        setBalance: jest.fn(),
        setWallet: jest.fn(),
    }),
}));

const consumerContract = {
    schema_version: 1,
    status: 'approved',
    classification: 'digital_service_with_prepaid_internal_units',
    disclosure_id: 'gsubs-b2c-el-v1',
    disclosure_sha256: 'a'.repeat(64),
    locale: 'el' as const,
    policy_version: 'policy-v1',
    terms_version: 'terms-v1',
    withdrawal_notice_version: 'withdrawal-v1',
    confirmation_template_version: 'confirmation-v1',
    terms_url: '/terms',
    withdrawal_url: '/account/billing',
    model_withdrawal_form_url: '/terms#withdrawal',
    trader: {
        legal_name: 'Ascentia G.P.',
        trading_name: 'Ascentia',
        service: 'GSUBS',
        address_line_1: 'Agias Varvaras 4',
        postal_code: '16452',
        city: 'Argiroupoli, Athens',
        country: 'GR' as const,
        support_email: 'info@ascentia-gp.com',
        support_phone: '+30 698 756 4060',
        website: 'https://ascentia-gp.com/',
    },
    content: {
        title: 'Consumer contract',
        service_description: 'Digital processing service.',
        credit_description: 'Prepaid internal units.',
        purchase_terms: 'One-off purchase.',
        delivery_timing: 'Credits after confirmed payment.',
        validity_and_transfer: 'No automatic expiry or transfer mechanism.',
        functionality: 'Processing consumes credits.',
        compatibility: 'Supported browser required.',
        withdrawal_notice: 'Fourteen-day withdrawal notice.',
        manual_review_notice: 'Pending manual review.',
    },
    required_acceptances: {
        terms: 'Accept the terms and pre-contract information.',
        immediate_performance: 'Request immediate performance.',
        withdrawal_consequences: 'Acknowledge the withdrawal consequences.',
    },
};

const catalog = {
    catalog_version: 'video-credits-v1',
    currency: 'eur',
    billing_country_scope: ['GR'] as Array<'GR'>,
    checkout_enabled: true,
    consumer_contract_status: 'approved' as const,
    consumer_contract: consumerContract,
    packages: [
        { key: 'starter', credits: 100, amount_eur_cents: 100, featured: false },
        { key: 'creator', credits: 350, amount_eur_cents: 300, featured: true },
        { key: 'studio', credits: 1200, amount_eur_cents: 1000, featured: false },
    ],
    video_pricing: [
        { key: 'up_to_3m', max_duration_seconds: 180, credits: 30 },
        { key: 'up_to_6m', max_duration_seconds: 360, credits: 60 },
        { key: 'up_to_10m', max_duration_seconds: 600, credits: 100 },
    ],
};

function acceptAllConsumerTerms(): void {
    screen.getAllByRole('checkbox').forEach((checkbox) => {
        fireEvent.click(checkbox);
    });
}

function deferred<T>() {
    let resolve: (value: T) => void = () => undefined;
    const promise = new Promise<T>((promiseResolve) => {
        resolve = promiseResolve;
    });
    return { promise, resolve };
}

function FocusHarness() {
    const [isOpen, setIsOpen] = useState(false);
    return (
        <>
            <button type="button" onClick={() => setIsOpen(true)}>
                Launch purchase
            </button>
            <CreditPurchaseDialog
                isOpen={isOpen}
                isAuthenticated
                onClose={() => setIsOpen(false)}
                onRequireAuth={jest.fn()}
            />
        </>
    );
}

describe('CreditPurchaseDialog', () => {
    const onClose = jest.fn();
    const onRequireAuth = jest.fn();
    const onRedirect = jest.fn();

    beforeEach(() => {
        jest.clearAllMocks();
        mockPaidCreditLegalPublication.approved = true;
        mockLocaleState.locale = 'el';
        (api.getCreditCatalog as jest.Mock).mockResolvedValue(catalog);
        (api.createCreditCheckout as jest.Mock).mockResolvedValue({
            purchase_id: 'purchase-1',
            checkout_session_id: 'cs_test_123',
            checkout_url: 'https://checkout.stripe.com/c/pay/cs_test_123',
            status: 'pending',
        });
    });

    it('locks the root and body scrollers for mobile WebKit', () => {
        const scrollTo = jest.fn();
        Object.defineProperty(window, 'scrollTo', {
            configurable: true,
            value: scrollTo,
        });
        Object.defineProperty(window, 'scrollX', { configurable: true, value: 0 });
        Object.defineProperty(window, 'scrollY', { configurable: true, value: 220 });

        const view = render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
            />,
        );

        expect(document.documentElement.style.overflow).toBe('hidden');
        expect(document.body.style.overflow).toBe('hidden');
        expect(document.body.style.position).toBe('fixed');
        expect(document.body.style.top).toBe('-220px');

        view.unmount();
        expect(document.documentElement.style.overflow).toBe('');
        expect(document.body.style.overflow).toBe('');
        expect(document.body.style.position).toBe('');
        expect(scrollTo).toHaveBeenCalledWith(0, 220);
    });

    it('accepts only the exact Stripe hosted-checkout origin', () => {
        expect(isAllowedStripeCheckoutUrl('https://checkout.stripe.com/c/pay/cs_test_123')).toBe(true);
        expect(isAllowedStripeCheckoutUrl('http://checkout.stripe.com/c/pay/test')).toBe(false);
        expect(isAllowedStripeCheckoutUrl('https://checkout.stripe.com.evil.example/test')).toBe(false);
        expect(isAllowedStripeCheckoutUrl('https://checkout.stripe.com@evil.example/test')).toBe(false);
        expect(isAllowedStripeCheckoutUrl('javascript:alert(1)')).toBe(false);
        expect(isAllowedStripeCheckoutUrl('not a URL')).toBe(false);
    });

    it('recommends the smallest sufficient package and starts one hosted checkout', async () => {
        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                requiredCredits={60}
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        const starter = await screen.findByRole('radio', { name: /starter/i });
        expect(starter).toBeChecked();
        expect(screen.getByText(/creditPurchaseMissing/)).toHaveTextContent('40');

        acceptAllConsumerTerms();
        fireEvent.click(screen.getByRole('button', { name: /creditPurchasePay/ }));

        await waitFor(() => {
            expect(api.createCreditCheckout).toHaveBeenCalledWith(
                'starter',
                expect.stringMatching(/^checkout-/),
                'video-credits-v1',
                'GR',
                {
                    disclosure_id: 'gsubs-b2c-el-v1',
                    disclosure_sha256: 'a'.repeat(64),
                    locale: 'el',
                    policy_version: 'policy-v1',
                    terms_version: 'terms-v1',
                    withdrawal_notice_version: 'withdrawal-v1',
                    terms_accepted: true,
                    immediate_performance_requested: true,
                    withdrawal_consequences_acknowledged: true,
                },
            );
            expect(onRedirect).toHaveBeenCalledWith(
                'https://checkout.stripe.com/c/pay/cs_test_123',
            );
        });
        expect(onRequireAuth).not.toHaveBeenCalled();
    });

    it('requires login before creating a checkout for an anonymous user', async () => {
        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated={false}
                requiredCredits={30}
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        await screen.findByRole('radio', { name: /starter/i });
        fireEvent.click(screen.getByRole('button', { name: 'creditPurchaseSignIn' }));

        expect(onRequireAuth).toHaveBeenCalledTimes(1);
        expect(api.createCreditCheckout).not.toHaveBeenCalled();
        expect(onRedirect).not.toHaveBeenCalled();
    });

    it('supports Escape, backdrop closing, and explicit package selection', async () => {
        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        const creator = await screen.findByRole('radio', { name: /creator/i });
        fireEvent.click(creator);
        expect(creator).toBeChecked();

        fireEvent.keyDown(document, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByTestId('credit-purchase-dialog'));
        expect(onClose).toHaveBeenCalledTimes(2);

        acceptAllConsumerTerms();
        fireEvent.click(screen.getByRole('button', { name: /creditPurchasePay/ }));

        await waitFor(() => {
            expect(api.createCreditCheckout).toHaveBeenCalledWith(
                'creator',
                expect.stringMatching(/^checkout-/),
                'video-credits-v1',
                'GR',
                expect.objectContaining({
                    terms_accepted: true,
                    immediate_performance_requested: true,
                    withdrawal_consequences_acknowledged: true,
                }),
            );
        });
    });

    // REGRESSION: custom role=radio buttons did not implement the keyboard
    // interaction required for a single-select radio group.
    it('uses native radios with wrapping arrow and Home/End navigation', async () => {
        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        const starter = await screen.findByRole('radio', { name: /starter/i });
        const creator = screen.getByRole('radio', { name: /creator/i });
        const studio = screen.getByRole('radio', { name: /studio/i });
        [starter, creator, studio].forEach((radio) => {
            expect(radio).toHaveAttribute('type', 'radio');
            expect(radio).toHaveAttribute('name', 'credit-package');
        });

        starter.focus();
        fireEvent.keyDown(starter, { key: 'ArrowRight' });
        expect(creator).toBeChecked();
        await waitFor(() => expect(creator).toHaveFocus());

        fireEvent.keyDown(creator, { key: 'End' });
        expect(studio).toBeChecked();
        await waitFor(() => expect(studio).toHaveFocus());

        fireEvent.keyDown(studio, { key: 'ArrowRight' });
        expect(starter).toBeChecked();
        await waitFor(() => expect(starter).toHaveFocus());
    });

    // REGRESSION: keyboard focus could leave the modal, and closing did not
    // restore focus to the control that opened it.
    it('traps focus, focuses the close control, and restores the opener', async () => {
        render(<FocusHarness />);

        const trigger = screen.getByRole('button', {
            name: 'Launch purchase',
        });
        trigger.focus();
        fireEvent.click(trigger);

        const closeButton = screen.getByRole('button', { name: 'closeLabel' });
        await waitFor(() => expect(closeButton).toHaveFocus());
        await screen.findByRole('radio', { name: /starter/i });
        const lastConsent = screen.getAllByRole('checkbox')[3];

        lastConsent.focus();
        fireEvent.keyDown(document, { key: 'Tab' });
        expect(closeButton).toHaveFocus();

        fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
        expect(lastConsent).toHaveFocus();

        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        await waitFor(() => expect(trigger).toHaveFocus());
    });

    it('surfaces a non-Error catalog failure without offering checkout', async () => {
        (api.getCreditCatalog as jest.Mock).mockRejectedValueOnce('catalog unavailable');

        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        expect(await screen.findByRole('alert')).toHaveTextContent('creditPurchaseLoadError');
        expect(screen.queryByRole('radio')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {
            name: /creditPurchase(?:Continue|Pay|SignIn)/,
        })).not.toBeInTheDocument();
        expect(api.createCreditCheckout).not.toHaveBeenCalled();
    });

    it('never follows a checkout URL that fails the allow-list', async () => {
        (api.createCreditCheckout as jest.Mock).mockResolvedValueOnce({
            purchase_id: 'purchase-1',
            checkout_session_id: 'cs_test_123',
            checkout_url: 'https://checkout.stripe.com.evil.example/cs_test_123',
            status: 'pending',
        });

        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        await screen.findByRole('radio', { name: /starter/i });
        acceptAllConsumerTerms();
        fireEvent.click(screen.getByRole('button', { name: /creditPurchasePay/ }));

        expect(await screen.findByRole('alert')).toHaveTextContent('creditPurchaseUnsafeRedirect');
        expect(onRedirect).not.toHaveBeenCalled();
    });

    it('fails closed when the server reports that checkout is disabled', async () => {
        (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
            ...catalog,
            checkout_enabled: false,
        });

        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        expect(await screen.findByRole('status')).toHaveTextContent('creditPurchaseNotEnabled');
        expect(screen.queryByRole('radio')).not.toBeInTheDocument();
        expect(screen.queryByText('€1.00')).not.toBeInTheDocument();
        expect(screen.queryByText('€3.00')).not.toBeInTheDocument();
        expect(screen.queryByText('€10.00')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {
            name: /creditPurchase(?:Continue|Pay|SignIn)/,
        })).not.toBeInTheDocument();
        expect(api.createCreditCheckout).not.toHaveBeenCalled();
    });

    it('fails closed unless the backend publishes an exact Greece-only billing scope', async () => {
        (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
            ...catalog,
            billing_country_scope: ['GR', 'CY'],
        });

        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        expect(await screen.findByRole('status')).toHaveTextContent(
            'creditPurchaseNotEnabled',
        );
        expect(screen.queryByRole('radio')).not.toBeInTheDocument();
        expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
        expect(api.createCreditCheckout).not.toHaveBeenCalled();
    });

    it('does not present draft wording as operative terms', async () => {
        (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
            ...catalog,
            checkout_enabled: true,
            consumer_contract: {
                ...consumerContract,
                status: 'draft_unapproved',
            },
        });

        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        expect(await screen.findByRole('status')).toHaveTextContent(
            'creditPurchaseNotEnabled',
        );
        expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
        expect(
            screen.queryByText(consumerContract.content.service_description),
        ).not.toBeInTheDocument();
        expect(screen.queryByRole('radio')).not.toBeInTheDocument();
        expect(screen.queryByText('€1.00')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {
            name: /creditPurchase(?:Continue|Pay|SignIn)/,
        })).not.toBeInTheDocument();
        expect(api.createCreditCheckout).not.toHaveBeenCalled();
    });

    it('also fails closed when frontend legal publication is unapproved', async () => {
        mockPaidCreditLegalPublication.approved = false;

        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        expect(await screen.findByRole('status')).toHaveTextContent(
            'creditPurchaseNotEnabled',
        );
        expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
        expect(screen.queryByRole('radio')).not.toBeInTheDocument();
        expect(screen.queryByText('€1.00')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {
            name: /creditPurchase(?:Continue|Pay|SignIn)/,
        })).not.toBeInTheDocument();
    });

    it('also fails closed when the backend approval status disagrees with the contract', async () => {
        (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
            ...catalog,
            consumer_contract_status: 'unavailable_unapproved',
        });

        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        expect(await screen.findByRole('status')).toHaveTextContent(
            'creditPurchaseNotEnabled',
        );
        expect(screen.queryByRole('radio')).not.toBeInTheDocument();
        expect(screen.queryByText('€1.00')).not.toBeInTheDocument();
        expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
        expect(api.createCreditCheckout).not.toHaveBeenCalled();
    });

    it('fails closed when the returned disclosure locale does not match the request', async () => {
        (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
            ...catalog,
            consumer_contract: {
                ...consumerContract,
                locale: 'en',
            },
        });

        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        expect(await screen.findByRole('status')).toHaveTextContent(
            'creditPurchaseNotEnabled',
        );
        expect(screen.queryByRole('radio')).not.toBeInTheDocument();
        expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
        expect(api.createCreditCheckout).not.toHaveBeenCalled();
    });

    it('requires Greece eligibility plus three distinct unchecked acceptances and does not let links toggle them', async () => {
        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        await screen.findByRole('radio', { name: /starter/i });
        const checkboxes = screen.getAllByRole('checkbox');
        expect(checkboxes).toHaveLength(4);
        checkboxes.forEach((checkbox) => expect(checkbox).not.toBeChecked());
        expect(screen.getByRole('note')).toHaveTextContent(
            'creditPurchaseGreeceOnlyNotice',
        );
        expect(screen.getByRole('checkbox', {
            name: 'creditPurchaseGreeceBillingConfirmation',
        })).not.toBeChecked();

        fireEvent.click(screen.getByRole('link', { name: 'creditPurchaseTermsLink' }));
        checkboxes.forEach((checkbox) => expect(checkbox).not.toBeChecked());

        fireEvent.click(checkboxes[0]);
        fireEvent.click(checkboxes[1]);
        fireEvent.click(checkboxes[2]);
        expect(screen.getByRole('button', { name: /creditPurchasePay/ })).toBeDisabled();
        fireEvent.click(checkboxes[3]);
        expect(screen.getByRole('button', { name: /creditPurchasePay/ })).toBeEnabled();
    });

    // REGRESSION: the dialog previously omitted canonical trader, functionality,
    // compatibility, and manual-review disclosure fields before consent.
    it('shows the complete canonical consumer disclosure before consent', async () => {
        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        await screen.findByRole('radio', { name: /starter/i });

        const disclosureTitle = screen.getByRole('heading', {
            name: consumerContract.content.title,
        });
        const traderName = screen.getByText(
            consumerContract.trader.legal_name,
        );
        const traderService = screen.getByText(
            `${consumerContract.trader.trading_name} · ${consumerContract.trader.service}`,
        );
        const traderAddress = screen.getByText(
            `${consumerContract.trader.address_line_1}, ${consumerContract.trader.postal_code} ${consumerContract.trader.city}, ${consumerContract.trader.country}`,
        );
        const traderEmail = screen.getByRole('link', {
            name: consumerContract.trader.support_email,
        });
        const traderPhone = screen.getByRole('link', {
            name: consumerContract.trader.support_phone,
        });
        const traderWebsite = screen.getByRole('link', {
            name: consumerContract.trader.website,
        });
        expect(traderEmail).toHaveAttribute(
            'href',
            `mailto:${consumerContract.trader.support_email}`,
        );
        expect(traderPhone).toHaveAttribute('href', 'tel:+306987564060');
        expect(traderWebsite).toHaveAttribute(
            'href',
            consumerContract.trader.website,
        );

        const firstConsent = screen.getAllByRole('checkbox')[0];
        const canonicalDisclosureElements = [
            traderName,
            traderService,
            traderAddress,
            traderEmail,
            traderPhone,
            traderWebsite,
            ...Object.values(consumerContract.content).map((text) => (
                screen.getByText(text)
            )),
        ];
        expect(disclosureTitle).toBeInTheDocument();
        canonicalDisclosureElements.forEach((element) => {
            expect(
                element.compareDocumentPosition(firstConsent)
                & Node.DOCUMENT_POSITION_FOLLOWING,
            ).toBeTruthy();
        });
    });

    it('clears every acceptance and rotates the intent when the package changes', async () => {
        render(
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />,
        );

        await screen.findByRole('radio', { name: /starter/i });
        acceptAllConsumerTerms();
        expect(screen.getByRole('button', { name: /creditPurchasePay/ })).toBeEnabled();

        fireEvent.click(screen.getByRole('radio', { name: /creator/i }));

        screen.getAllByRole('checkbox').forEach((checkbox) => {
            expect(checkbox).not.toBeChecked();
        });
        expect(screen.getByRole('button', { name: /creditPurchasePay/ })).toBeDisabled();
    });

    // REGRESSION: a locale change could leave the previous disclosure and its
    // checked consent visible while a new catalog version was still loading.
    it('does not carry consent across a deferred locale and disclosure change', async () => {
        const greekCatalog = deferred<CreditCatalogResponse>();
        const englishCatalog = deferred<CreditCatalogResponse>();
        (api.getCreditCatalog as jest.Mock)
            .mockReset()
            .mockReturnValueOnce(greekCatalog.promise)
            .mockReturnValueOnce(englishCatalog.promise);

        const renderDialog = () => (
            <CreditPurchaseDialog
                isOpen
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />
        );
        const view = render(renderDialog());

        await act(async () => {
            greekCatalog.resolve(catalog);
        });
        await screen.findByRole('radio', { name: /starter/i });
        acceptAllConsumerTerms();
        expect(screen.getByRole('button', {
            name: /creditPurchasePay/,
        })).toBeEnabled();

        mockLocaleState.locale = 'en';
        view.rerender(renderDialog());

        expect(screen.queryByRole('radio')).not.toBeInTheDocument();
        expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
        expect(screen.queryByRole('button', {
            name: /creditPurchasePay/,
        })).not.toBeInTheDocument();

        const changedCatalog = {
            ...catalog,
            consumer_contract: {
                ...consumerContract,
                disclosure_id: 'gsubs-b2c-en-v2',
                disclosure_sha256: 'b'.repeat(64),
                locale: 'en' as const,
                policy_version: 'policy-v2',
                terms_version: 'terms-v2',
                withdrawal_notice_version: 'withdrawal-v2',
            },
        };
        await act(async () => {
            englishCatalog.resolve(changedCatalog);
        });

        await screen.findByRole('radio', { name: /starter/i });
        screen.getAllByRole('checkbox').forEach((checkbox) => {
            expect(checkbox).not.toBeChecked();
        });
        expect(screen.getByRole('button', {
            name: /creditPurchasePay/,
        })).toBeDisabled();

        acceptAllConsumerTerms();
        fireEvent.click(screen.getByRole('button', {
            name: /creditPurchasePay/,
        }));
        await waitFor(() => {
            expect(api.createCreditCheckout).toHaveBeenCalledWith(
                'starter',
                expect.stringMatching(/^checkout-/),
                'video-credits-v1',
                'GR',
                expect.objectContaining({
                    disclosure_id: 'gsubs-b2c-en-v2',
                    disclosure_sha256: 'b'.repeat(64),
                    locale: 'en',
                    policy_version: 'policy-v2',
                    terms_version: 'terms-v2',
                    withdrawal_notice_version: 'withdrawal-v2',
                }),
            );
        });
    });

    // REGRESSION: because the dialog stayed mounted, reopening could briefly
    // reveal the previous catalog and checked acceptance state before effects ran.
    it('starts every reopen with an empty, unaccepted loading state', async () => {
        const reopenedCatalog = deferred<CreditCatalogResponse>();
        (api.getCreditCatalog as jest.Mock)
            .mockReset()
            .mockResolvedValueOnce(catalog)
            .mockReturnValueOnce(reopenedCatalog.promise);

        const renderDialog = (isOpen: boolean) => (
            <CreditPurchaseDialog
                isOpen={isOpen}
                isAuthenticated
                onClose={onClose}
                onRequireAuth={onRequireAuth}
                onRedirect={onRedirect}
            />
        );
        const view = render(renderDialog(true));

        await screen.findByRole('radio', { name: /starter/i });
        acceptAllConsumerTerms();
        expect(screen.getByRole('button', {
            name: /creditPurchasePay/,
        })).toBeEnabled();

        view.rerender(renderDialog(false));
        view.rerender(renderDialog(true));

        expect(screen.queryByRole('radio')).not.toBeInTheDocument();
        expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
        expect(screen.queryByText(
            consumerContract.content.service_description,
        )).not.toBeInTheDocument();

        await act(async () => {
            reopenedCatalog.resolve(catalog);
        });
        await screen.findByRole('radio', { name: /starter/i });
        screen.getAllByRole('checkbox').forEach((checkbox) => {
            expect(checkbox).not.toBeChecked();
        });
        expect(screen.getByRole('button', {
            name: /creditPurchasePay/,
        })).toBeDisabled();
    });
});
