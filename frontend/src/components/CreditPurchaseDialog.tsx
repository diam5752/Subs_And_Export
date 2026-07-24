'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CoinsIcon } from '@/components/icons';
import { Spinner } from '@/components/Spinner';
import { useI18n } from '@/context/I18nContext';
import { usePoints } from '@/context/PointsContext';
import {
    api,
    type CreditCatalogResponse,
    type CreditPackage,
} from '@/lib/api';
import { formatPoints } from '@/lib/points';

interface CreditPurchaseDialogProps {
    isOpen: boolean;
    isAuthenticated: boolean;
    requiredCredits?: number;
    onClose: () => void;
    onRequireAuth: () => void;
    onRedirect?: (checkoutUrl: string) => void;
}

export function isAllowedStripeCheckoutUrl(value: string): boolean {
    try {
        const url = new URL(value);
        return url.origin === 'https://checkout.stripe.com'
            && url.username === ''
            && url.password === '';
    } catch {
        return false;
    }
}

function checkoutIdempotencyKey(): string {
    const random = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `checkout-${random}`;
}

export function CreditPurchaseDialog({
    isOpen,
    isAuthenticated,
    requiredCredits = 0,
    onClose,
    onRequireAuth,
    onRedirect = (checkoutUrl) => window.location.assign(checkoutUrl),
}: CreditPurchaseDialogProps) {
    const { t } = useI18n();
    const {
        balance,
        promotionalBalance,
        reversalDebt,
        aiSpendableBalance,
    } = usePoints();
    const [catalog, setCatalog] = useState<CreditCatalogResponse | null>(null);
    const [selectedKey, setSelectedKey] = useState('');
    const [acceptedTerms, setAcceptedTerms] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [isCheckingOut, setIsCheckingOut] = useState(false);
    const [error, setError] = useState('');
    const idempotencyKeyRef = useRef(checkoutIdempotencyKey());
    const closeButtonRef = useRef<HTMLButtonElement>(null);

    const close = useCallback(() => {
        onClose();
    }, [onClose]);

    useEffect(() => {
        if (!isOpen) return;
        let active = true;
        idempotencyKeyRef.current = checkoutIdempotencyKey();
        queueMicrotask(() => {
            if (!active) return;
            setIsLoading(true);
            setError('');
            setAcceptedTerms(false);
        });
        void api.getCreditCatalog()
            .then((result) => {
                if (!active) return;
                setCatalog(result);
                const missing = Math.max(0, requiredCredits - (aiSpendableBalance ?? 0));
                const recommended = result.packages.find((item) => item.credits >= missing)
                    ?? result.packages[result.packages.length - 1];
                setSelectedKey(recommended?.key ?? '');
            })
            .catch((catalogError: unknown) => {
                if (!active) return;
                setError(catalogError instanceof Error ? catalogError.message : t('creditPurchaseLoadError'));
            })
            .finally(() => {
                if (active) setIsLoading(false);
            });

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') close();
        };
        document.addEventListener('keydown', handleKeyDown);
        document.body.style.overflow = 'hidden';
        queueMicrotask(() => closeButtonRef.current?.focus());
        return () => {
            active = false;
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
        };
    }, [aiSpendableBalance, close, isOpen, requiredCredits, t]);

    const selectedPackage = useMemo(
        () => catalog?.packages.find((item) => item.key === selectedKey) ?? null,
        [catalog, selectedKey],
    );
    const missingCredits = Math.max(0, requiredCredits - (aiSpendableBalance ?? 0));

    const handlePackageChange = (packageKey: string) => {
        setSelectedKey(packageKey);
        setError('');
        idempotencyKeyRef.current = checkoutIdempotencyKey();
    };

    const handleCheckout = async () => {
        if (!isAuthenticated) {
            onRequireAuth();
            return;
        }
        if (!selectedPackage || !acceptedTerms || !catalog?.checkout_enabled) return;
        setIsCheckingOut(true);
        setError('');
        try {
            const result = await api.createCreditCheckout(
                selectedPackage.key,
                idempotencyKeyRef.current,
            );
            if (!result.checkout_url || !isAllowedStripeCheckoutUrl(result.checkout_url)) {
                throw new Error(t('creditPurchaseUnsafeRedirect'));
            }
            onRedirect(result.checkout_url);
        } catch (checkoutError) {
            setError(checkoutError instanceof Error ? checkoutError.message : t('creditPurchaseError'));
            setIsCheckingOut(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="credit-purchase-title"
            className="fixed inset-0 z-[80] flex items-end justify-center bg-black/65 px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] backdrop-blur-md sm:items-center sm:p-8"
            onClick={() => {
                if (!isCheckingOut) close();
            }}
            data-testid="credit-purchase-dialog"
        >
            <div
                className="relative max-h-[94dvh] w-full max-w-[760px] overflow-y-auto rounded-[28px] border border-white/10 bg-[#0a0b0e] text-white shadow-[0_30px_100px_rgba(0,0,0,0.65)]"
                onClick={(event) => event.stopPropagation()}
            >
                <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-white/10 bg-[#0a0b0e]/95 px-5 py-5 backdrop-blur-xl sm:px-8">
                    <div>
                        <span className="text-[10px] font-bold uppercase tracking-[0.22em] text-sky-400">
                            {t('creditPurchaseKicker')}
                        </span>
                        <h2 id="credit-purchase-title" className="mt-2 text-2xl font-bold tracking-[-0.04em] sm:text-3xl">
                            {t('creditPurchaseTitle')}
                        </h2>
                        <p className="mt-2 max-w-xl text-sm leading-6 text-[#9aa2ae]">
                            {t('creditPurchaseDescription')}
                        </p>
                    </div>
                    <button
                        ref={closeButtonRef}
                        type="button"
                        onClick={close}
                        disabled={isCheckingOut}
                        className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-white/10 text-[#9aa2ae] transition hover:bg-white/5 hover:text-white disabled:opacity-40"
                        aria-label={t('closeLabel')}
                    >
                        <span aria-hidden="true">✕</span>
                    </button>
                </div>

                <div className="space-y-6 px-5 py-6 sm:px-8 sm:py-8">
                    <div className="grid gap-3 rounded-2xl border border-white/10 bg-white/[0.035] p-4 sm:grid-cols-3">
                        <WalletMetric label={t('creditPurchaseTotalBalance')} value={balance} />
                        <WalletMetric label={t('creditPurchaseCloudBalance')} value={aiSpendableBalance} accent />
                        <WalletMetric label={t('creditPurchasePromoBalance')} value={promotionalBalance} />
                    </div>

                    {requiredCredits > 0 && (
                        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-sky-400/25 bg-sky-400/[0.07] px-4 py-3">
                            <span className="text-sm text-[#cbd4df]">{t('creditPurchaseRequired')}</span>
                            <div className="flex items-center gap-4 text-sm">
                                <span>{formatPoints(requiredCredits)} {t('creditsLabel')}</span>
                                <strong className="text-sky-300">
                                    {t('creditPurchaseMissing', { count: missingCredits })}
                                </strong>
                            </div>
                        </div>
                    )}

                    {typeof reversalDebt === 'number' && reversalDebt > 0 && (
                        <p role="alert" className="rounded-2xl border border-amber-400/25 bg-amber-400/[0.08] px-4 py-3 text-sm leading-6 text-amber-100">
                            {t('creditPurchaseDebtNotice', { count: reversalDebt })}
                        </p>
                    )}

                    {isLoading ? (
                        <div className="grid min-h-52 place-items-center">
                            <Spinner className="h-6 w-6" />
                        </div>
                    ) : (
                        <div
                            role="radiogroup"
                            aria-label={t('creditPurchasePackagesLabel')}
                            className="grid gap-3 sm:grid-cols-3"
                        >
                            {catalog?.packages.map((creditPackage) => (
                                <PackageOption
                                    key={creditPackage.key}
                                    creditPackage={creditPackage}
                                    packageLabel={
                                        creditPackage.key === 'starter'
                                            ? t('creditPackageStarter')
                                            : creditPackage.key === 'core'
                                                ? t('creditPackageCore')
                                                : creditPackage.key === 'pro'
                                                    ? t('creditPackagePro')
                                                    : creditPackage.key
                                    }
                                    selected={creditPackage.key === selectedKey}
                                    onSelect={() => handlePackageChange(creditPackage.key)}
                                    featuredLabel={t('creditPurchasePopular')}
                                    creditsLabel={t('creditsLabel')}
                                />
                            ))}
                        </div>
                    )}

                    {catalog && !catalog.checkout_enabled && (
                        <p role="status" className="rounded-2xl border border-amber-300/20 bg-amber-300/[0.07] px-4 py-3 text-sm leading-6 text-amber-100">
                            {t('creditPurchaseNotEnabled')}
                        </p>
                    )}

                    {error && (
                        <p role="alert" className="rounded-2xl border border-red-400/25 bg-red-400/[0.08] px-4 py-3 text-sm text-red-100">
                            {error}
                        </p>
                    )}

                    <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-white/10 p-4 text-sm leading-6 text-[#b8c0cb]">
                        <input
                            type="checkbox"
                            checked={acceptedTerms}
                            onChange={(event) => setAcceptedTerms(event.target.checked)}
                            className="mt-1 h-4 w-4 rounded border-white/20 accent-sky-400"
                        />
                        <span>
                            {t('creditPurchaseTermsPrefix')}{' '}
                            <a href="/terms" target="_blank" rel="noopener noreferrer" className="font-semibold text-white underline decoration-white/30 underline-offset-4">
                                {t('creditPurchaseTermsLink')}
                            </a>
                        </span>
                    </label>

                    <div className="flex flex-col gap-3 border-t border-white/10 pt-5 sm:flex-row sm:items-center sm:justify-between">
                        <p className="flex items-center gap-2 text-xs leading-5 text-[#89929f]">
                            <span className="grid h-7 w-7 place-items-center rounded-full bg-white/5 text-sky-300" aria-hidden="true">↗</span>
                            {t('creditPurchaseStripeNote')}
                        </p>
                        <button
                            type="button"
                            onClick={() => void handleCheckout()}
                            disabled={
                                isCheckingOut
                                || isLoading
                                || (isAuthenticated && (!selectedPackage || !acceptedTerms || !catalog?.checkout_enabled))
                            }
                            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-sky-500 px-6 font-bold text-white shadow-[0_14px_36px_rgba(14,165,233,0.22)] transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                            {isCheckingOut && <Spinner className="h-4 w-4" />}
                            {!isAuthenticated
                                ? t('creditPurchaseSignIn')
                                : selectedPackage
                                    ? t('creditPurchasePay', {
                                        amount: (selectedPackage.amount_eur_cents / 100).toFixed(2),
                                    })
                                    : t('creditPurchaseContinue')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

function WalletMetric({
    label,
    value,
    accent = false,
}: {
    label: string;
    value: number | null;
    accent?: boolean;
}) {
    return (
        <div>
            <span className="block text-[10px] font-bold uppercase tracking-[0.15em] text-[#7f8895]">{label}</span>
            <strong className={`mt-1 flex items-center gap-2 text-lg ${accent ? 'text-sky-300' : 'text-white'}`}>
                <CoinsIcon className="h-4 w-4" />
                {value === null ? '—' : formatPoints(value)}
            </strong>
        </div>
    );
}

function PackageOption({
    creditPackage,
    packageLabel,
    selected,
    onSelect,
    featuredLabel,
    creditsLabel,
}: {
    creditPackage: CreditPackage;
    packageLabel: string;
    selected: boolean;
    onSelect: () => void;
    featuredLabel: string;
    creditsLabel: string;
}) {
    return (
        <button
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={onSelect}
            className={`relative min-h-44 rounded-2xl border p-5 text-left transition ${
                selected
                    ? 'border-sky-400 bg-sky-400/[0.09] shadow-[0_0_0_1px_rgba(56,189,248,0.25)]'
                    : 'border-white/10 bg-white/[0.025] hover:border-white/20 hover:bg-white/[0.045]'
            }`}
        >
            {creditPackage.featured && (
                <span className="absolute right-3 top-3 rounded-full bg-sky-400 px-2 py-1 text-[9px] font-black uppercase tracking-[0.12em] text-[#071016]">
                    {featuredLabel}
                </span>
            )}
            <span className="block text-xs font-bold uppercase tracking-[0.16em] text-[#8d96a3]">
                {packageLabel}
            </span>
            <strong className="mt-6 block text-3xl tracking-[-0.05em]">
                €{(creditPackage.amount_eur_cents / 100).toFixed(2)}
            </strong>
            <span className="mt-3 flex items-center gap-2 text-sm font-semibold text-[#dbe3ec]">
                <CoinsIcon className="h-4 w-4 text-sky-300" />
                {formatPoints(creditPackage.credits)} {creditsLabel}
            </span>
        </button>
    );
}
