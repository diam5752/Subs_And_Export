import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import {
    CreditPurchaseDialog,
    isAllowedStripeCheckoutUrl,
} from '@/components/CreditPurchaseDialog';
import { api } from '@/lib/api';

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
        useI18n: () => ({ t: translate }),
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

const catalog = {
    catalog_version: 'video-credits-v1',
    currency: 'eur',
    checkout_enabled: true,
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

describe('CreditPurchaseDialog', () => {
    const onClose = jest.fn();
    const onRequireAuth = jest.fn();
    const onRedirect = jest.fn();

    beforeEach(() => {
        jest.clearAllMocks();
        (api.getCreditCatalog as jest.Mock).mockResolvedValue(catalog);
        (api.createCreditCheckout as jest.Mock).mockResolvedValue({
            purchase_id: 'purchase-1',
            checkout_session_id: 'cs_test_123',
            checkout_url: 'https://checkout.stripe.com/c/pay/cs_test_123',
            status: 'pending',
        });
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
        expect(starter).toHaveAttribute('aria-checked', 'true');
        expect(screen.getByText(/creditPurchaseMissing/)).toHaveTextContent('40');

        fireEvent.click(screen.getByRole('checkbox'));
        fireEvent.click(screen.getByRole('button', { name: /creditPurchasePay/ }));

        await waitFor(() => {
            expect(api.createCreditCheckout).toHaveBeenCalledWith(
                'starter',
                expect.stringMatching(/^checkout-/),
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
        expect(creator).toHaveAttribute('aria-checked', 'true');

        fireEvent.keyDown(document, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByTestId('credit-purchase-dialog'));
        expect(onClose).toHaveBeenCalledTimes(2);

        fireEvent.click(screen.getByRole('checkbox'));
        fireEvent.click(screen.getByRole('button', { name: /creditPurchasePay/ }));

        await waitFor(() => {
            expect(api.createCreditCheckout).toHaveBeenCalledWith(
                'creator',
                expect.stringMatching(/^checkout-/),
            );
        });
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
        expect(screen.getByRole('button', { name: 'creditPurchaseContinue' })).toBeDisabled();
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
        fireEvent.click(screen.getByRole('checkbox'));
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
        fireEvent.click(screen.getByRole('checkbox'));
        expect(screen.getByRole('button', { name: /creditPurchasePay/ })).toBeDisabled();
        expect(api.createCreditCheckout).not.toHaveBeenCalled();
    });
});
