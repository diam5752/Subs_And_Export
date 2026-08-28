'use client';

import React, {
    useCallback,
    useEffect,
    useId,
    useMemo,
    useRef,
    useState,
} from 'react';
import { CoinsIcon } from '@/components/icons';
import { Spinner } from '@/components/Spinner';
import { useI18n } from '@/context/I18nContext';
import { usePoints } from '@/context/PointsContext';
import { useDocumentScrollLock } from '@/hooks/useDocumentScrollLock';
import {
    api,
    type CreditCatalogResponse,
    type CreditPackage,
} from '@/lib/api';
import { formatPoints } from '@/lib/points';
import { paidCreditLegalPublicationIsApproved } from '@/lib/paidCreditLegal';

interface CreditPurchaseDialogProps {
    isOpen: boolean;
    isAuthenticated: boolean;
    requiredCredits?: number;
    onClose: () => void;
    onRequireAuth: () => void;
    onRedirect?: (checkoutUrl: string) => void;
}

type I18nValue = ReturnType<typeof useI18n>;
type ConsumerContract = NonNullable<
    CreditCatalogResponse['consumer_contract']
>;

interface OpenCreditPurchaseDialogProps
    extends Omit<CreditPurchaseDialogProps, 'isOpen'> {
    locale: I18nValue['locale'];
    t: I18nValue['t'];
}

interface ContractConsentState {
    disclosureIdentity: string;
    combinedAccepted: boolean;
}

const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    'summary',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

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

function contractDisclosureIdentity(contract: ConsumerContract): string {
    return JSON.stringify([
        contract.disclosure_id,
        contract.disclosure_sha256,
        contract.locale,
        contract.policy_version,
        contract.terms_version,
        contract.withdrawal_notice_version,
    ]);
}

function focusableElements(container: HTMLElement): HTMLElement[] {
    return Array.from(
        container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    ).filter((element) => (
        !element.hasAttribute('hidden')
        && element.getAttribute('aria-hidden') !== 'true'
    ));
}

export function CreditPurchaseDialog(
    props: CreditPurchaseDialogProps,
) {
    const { locale, t } = useI18n();
    const { isOpen, ...openProps } = props;

    if (!isOpen) return null;

    return (
        <OpenCreditPurchaseDialog
            key={locale}
            {...openProps}
            locale={locale}
            t={t}
        />
    );
}

function OpenCreditPurchaseDialog({
    isAuthenticated,
    requiredCredits = 0,
    onClose,
    onRequireAuth,
    locale,
    t,
    onRedirect = (checkoutUrl) => window.location.assign(checkoutUrl),
}: OpenCreditPurchaseDialogProps) {
    const {
        reversalDebt,
        aiSpendableBalance,
    } = usePoints();
    const [catalog, setCatalog] = useState<CreditCatalogResponse | null>(null);
    const [selectedKey, setSelectedKey] = useState('');
    const [consentState, setConsentState] = useState<
        ContractConsentState | null
    >(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isCheckingOut, setIsCheckingOut] = useState(false);
    const [error, setError] = useState('');
    const idempotencyKeyRef = useRef(checkoutIdempotencyKey());
    const onCloseRef = useRef(onClose);
    const closeButtonRef = useRef<HTMLButtonElement>(null);
    const dialogRef = useRef<HTMLDivElement>(null);
    const packageRadioRefs = useRef(new Map<string, HTMLInputElement>());
    const recommendationGapRef = useRef(
        Math.max(0, requiredCredits - (aiSpendableBalance ?? 0)),
    );
    const combinedConsentId = useId();
    const consentConsequenceId = useId();

    useDocumentScrollLock(true);

    useEffect(() => {
        onCloseRef.current = onClose;
    }, [onClose]);

    const close = useCallback(() => {
        onCloseRef.current();
    }, []);

    useEffect(() => {
        let active = true;
        void api.getCreditCatalog(locale)
            .then((result) => {
                if (!active) return;
                setCatalog(result);
                const recommended = result.packages.find(
                    (item) => item.credits >= recommendationGapRef.current,
                )
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
        return () => {
            active = false;
        };
    }, [locale, t]);

    useEffect(() => {
        const previouslyFocused = (
            document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null
        );
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                close();
                return;
            }
            if (event.key !== 'Tab' || !dialogRef.current) return;

            const focusable = focusableElements(dialogRef.current);
            if (focusable.length === 0) {
                event.preventDefault();
                dialogRef.current.focus();
                return;
            }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            const activeElement = document.activeElement;
            const focusIsInside = (
                activeElement instanceof Node
                && dialogRef.current.contains(activeElement)
            );
            if (event.shiftKey && (!focusIsInside || activeElement === first)) {
                event.preventDefault();
                last.focus();
            } else if (
                !event.shiftKey
                && (!focusIsInside || activeElement === last)
            ) {
                event.preventDefault();
                first.focus();
            }
        };
        document.addEventListener('keydown', handleKeyDown);
        queueMicrotask(() => closeButtonRef.current?.focus());
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            queueMicrotask(() => {
                if (previouslyFocused?.isConnected) {
                    previouslyFocused.focus();
                }
            });
        };
    }, [close]);

    const selectedPackage = useMemo(
        () => catalog?.packages.find((item) => item.key === selectedKey) ?? null,
        [catalog, selectedKey],
    );
    const consumerContract = catalog?.consumer_contract ?? null;
    const paidSalesDisclosureReady = Boolean(
        catalog
        && Array.isArray(catalog.billing_country_scope)
        && catalog.billing_country_scope.length === 1
        && catalog.billing_country_scope[0] === 'GR'
        && catalog.consumer_contract_status === 'approved'
        && consumerContract?.status === 'approved'
        && consumerContract.locale === locale
        && paidCreditLegalPublicationIsApproved()
    );
    const paidSalesAvailable = Boolean(
        catalog?.checkout_enabled && paidSalesDisclosureReady,
    );
    const paidSalesReviewMode = Boolean(
        !catalog?.checkout_enabled
        && paidSalesDisclosureReady
        && process.env.NEXT_PUBLIC_PAID_CREDITS_UI_REVIEW === '1'
    );
    const paidSalesVisible = paidSalesAvailable || paidSalesReviewMode;
    const disclosureIdentity = consumerContract
        ? contractDisclosureIdentity(consumerContract)
        : null;
    const consentMatchesDisclosure = (
        disclosureIdentity !== null
        && consentState?.disclosureIdentity === disclosureIdentity
    );
    const combinedConsentAccepted = Boolean(
        consentMatchesDisclosure && consentState?.combinedAccepted,
    );
    const termsBaseUrl = consumerContract
        ? consumerContract.terms_url.split('#')[0]
        : '/terms';
    const paidCreditsTermsUrl = `${termsBaseUrl}#seller`;
    const withdrawalRightsUrl = `${termsBaseUrl}#withdrawal-rights`;
    const missingCredits = Math.max(0, requiredCredits - (aiSpendableBalance ?? 0));

    const handlePackageChange = (packageKey: string) => {
        setSelectedKey(packageKey);
        setError('');
        setConsentState(null);
        idempotencyKeyRef.current = checkoutIdempotencyKey();
    };

    const updateConsent = (checked: boolean) => {
        if (!disclosureIdentity) return;
        setConsentState({
            disclosureIdentity,
            combinedAccepted: checked,
        });
    };

    const handlePackageKeyDown = (
        event: React.KeyboardEvent<HTMLInputElement>,
        packageIndex: number,
    ) => {
        const packages = catalog?.packages ?? [];
        if (packages.length === 0) return;

        let nextIndex: number | null = null;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
            nextIndex = (packageIndex + 1) % packages.length;
        } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
            nextIndex = (
                packageIndex - 1 + packages.length
            ) % packages.length;
        } else if (event.key === 'Home') {
            nextIndex = 0;
        } else if (event.key === 'End') {
            nextIndex = packages.length - 1;
        }
        if (nextIndex === null) return;

        event.preventDefault();
        const nextPackage = packages[nextIndex];
        handlePackageChange(nextPackage.key);
        queueMicrotask(() => {
            packageRadioRefs.current.get(nextPackage.key)?.focus();
        });
    };

    const handleCheckout = async () => {
        if (!isAuthenticated) {
            onRequireAuth();
            return;
        }
        if (
            !selectedPackage
            || !catalog
            || !consumerContract
            || !paidSalesAvailable
            || !disclosureIdentity
            || consentState?.disclosureIdentity !== disclosureIdentity
            || !combinedConsentAccepted
        ) return;
        setIsCheckingOut(true);
        setError('');
        try {
            const result = await api.createCreditCheckout(
                selectedPackage.key,
                idempotencyKeyRef.current,
                catalog.catalog_version,
                'GR',
                {
                    disclosure_id: consumerContract.disclosure_id,
                    disclosure_sha256: (
                        consumerContract.disclosure_sha256
                    ),
                    locale: consumerContract.locale,
                    policy_version: consumerContract.policy_version,
                    terms_version: consumerContract.terms_version,
                    withdrawal_notice_version: (
                        consumerContract.withdrawal_notice_version
                    ),
                    terms_accepted: true,
                    immediate_performance_requested: true,
                    withdrawal_consequences_acknowledged: true,
                },
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

    return (
        <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="credit-purchase-title"
            tabIndex={-1}
            className="fixed inset-0 z-[80] flex items-end justify-center bg-black/65 px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] backdrop-blur-md sm:items-center sm:p-8"
            onClick={() => {
                if (!isCheckingOut) close();
            }}
            data-testid="credit-purchase-dialog"
        >
            <div
                className="relative max-h-[94dvh] w-full max-w-[680px] overflow-y-auto rounded-[26px] border border-white/10 bg-[#0a0b0e] text-white shadow-[0_30px_100px_rgba(0,0,0,0.65)]"
                onClick={(event) => event.stopPropagation()}
            >
                <div className="sticky top-0 z-10 flex items-start justify-between gap-4 bg-[#0a0b0e]/95 px-5 pt-5 pb-3 backdrop-blur-xl sm:px-7 sm:pt-7">
                    <div>
                        <span className="text-[10px] font-bold uppercase tracking-[0.22em] text-sky-400">
                            {t('creditPurchaseKicker')}
                        </span>
                        <h2 id="credit-purchase-title" className="mt-2 text-2xl font-bold tracking-[-0.04em] sm:text-3xl">
                            {t('creditPurchaseTitle')}
                        </h2>
                    </div>
                    <button
                        ref={closeButtonRef}
                        type="button"
                        onClick={close}
                        disabled={isCheckingOut}
                        className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-white/15 text-[#9aa2ae] transition hover:border-white/25 hover:bg-white/5 hover:text-white disabled:opacity-40"
                        aria-label={t('closeLabel')}
                    >
                        <span aria-hidden="true">✕</span>
                    </button>
                </div>

                <div className="space-y-5 px-5 pt-3 pb-5 sm:px-7 sm:pb-7">
                    <div
                        data-testid="credit-purchase-available-balance"
                        className="inline-flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.025] px-3.5 py-2.5"
                    >
                        <CoinsIcon className="h-4 w-4 text-sky-400" />
                        <strong className="text-base text-white">
                            {aiSpendableBalance === null
                                ? '—'
                                : formatPoints(aiSpendableBalance)}
                        </strong>
                        <span className="text-sm text-[#b2bac5]">
                            {t('creditPurchaseAvailableNow')}
                        </span>
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
                    ) : paidSalesVisible ? (
                        <div
                            role="radiogroup"
                            aria-label={t('creditPurchasePackagesLabel')}
                            className="grid grid-cols-3 gap-2.5"
                        >
                            {catalog?.packages.map((creditPackage, index) => (
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
                                    onKeyDown={(event) => {
                                        handlePackageKeyDown(event, index);
                                    }}
                                    inputRef={(element) => {
                                        if (element) {
                                            packageRadioRefs.current.set(
                                                creditPackage.key,
                                                element,
                                            );
                                        } else {
                                            packageRadioRefs.current.delete(
                                                creditPackage.key,
                                            );
                                        }
                                    }}
                                    creditsLabel={t('creditsLabel')}
                                />
                            ))}
                        </div>
                    ) : null}

                    {catalog && !paidSalesVisible && (
                        <p role="status" className="rounded-2xl border border-amber-300/20 bg-amber-300/[0.07] px-4 py-3 text-sm leading-6 text-amber-100">
                            {t('creditPurchaseNotEnabled')}
                        </p>
                    )}

                    {error && (
                        <p role="alert" className="rounded-2xl border border-red-400/25 bg-red-400/[0.08] px-4 py-3 text-sm text-red-100">
                            {error}
                        </p>
                    )}

                    {catalog && consumerContract && paidSalesVisible && (
                        <div className="space-y-4">
                            <div
                                role="note"
                                className="flex flex-wrap items-center gap-x-2.5 gap-y-2 border-y border-white/10 py-3 text-xs text-[#9da6b2]"
                            >
                                <span>{t('creditPurchaseBillingScope')}</span>
                                <span aria-hidden="true">·</span>
                                <span>{t('creditPurchaseVatIncluded')}</span>
                                <span aria-hidden="true">·</span>
                                <span>{t('creditPurchaseOneOff')}</span>
                                <span className="hidden h-4 w-px bg-white/10 sm:block" aria-hidden="true" />
                                <a
                                    href={paidCreditsTermsUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="font-semibold text-white underline decoration-white/30 underline-offset-4 transition hover:decoration-white"
                                >
                                    {t('creditPurchaseTermsLink')}
                                </a>
                                <a
                                    href={withdrawalRightsUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="font-semibold text-white underline decoration-white/30 underline-offset-4 transition hover:decoration-white"
                                >
                                    {t('creditPurchaseWithdrawalDetailsLink')}
                                </a>
                            </div>
                            <div className="flex items-start gap-3">
                                <input
                                    id={combinedConsentId}
                                    type="checkbox"
                                    checked={combinedConsentAccepted}
                                    aria-describedby={consentConsequenceId}
                                    onChange={(event) => {
                                        updateConsent(event.target.checked);
                                    }}
                                    className="mt-0.5 h-5 w-5 shrink-0 rounded border-white/20 accent-sky-400"
                                />
                                <div>
                                    <label
                                        htmlFor={combinedConsentId}
                                        className="cursor-pointer text-sm font-medium leading-5 text-[#e6eaf0]"
                                    >
                                        {t('creditPurchaseConsentRequest')}
                                    </label>
                                    <p
                                        id={consentConsequenceId}
                                        className="mt-1 text-xs leading-5 text-[#8f98a5]"
                                    >
                                        {t('creditPurchaseConsentConsequence')}
                                    </p>
                                    <details className="group mt-1.5 text-xs text-[#8f98a5]">
                                        <summary className="inline-flex cursor-pointer list-none items-center gap-1 font-medium text-[#c8d0da] underline decoration-white/20 underline-offset-4 transition hover:text-white [&::-webkit-details-marker]:hidden">
                                            {t('creditPurchaseExactConsentDetails')}
                                            <span
                                                aria-hidden="true"
                                                className="text-[10px] transition group-open:rotate-180"
                                            >
                                                ▾
                                            </span>
                                        </summary>
                                        <ul className="mt-2 space-y-1.5 border-l border-white/10 pl-4 text-[11px] leading-5">
                                            {Object.entries(
                                                consumerContract.required_acceptances,
                                            ).map(([key, acceptance]) => (
                                                <li key={key}>{acceptance}</li>
                                            ))}
                                        </ul>
                                    </details>
                                </div>
                            </div>
                        </div>
                    )}

                    {paidSalesVisible && (
                        <div className="flex flex-col border-t border-white/10 pt-5 sm:flex-row sm:justify-end">
                            <button
                                type="button"
                                onClick={() => void handleCheckout()}
                                disabled={
                                    isCheckingOut
                                    || isLoading
                                    || (
                                        isAuthenticated
                                        && (
                                            !selectedPackage
                                            || !combinedConsentAccepted
                                        )
                                    )
                                }
                                className="inline-flex min-h-12 shrink-0 items-center justify-center gap-2 rounded-xl bg-sky-500 px-5 text-sm font-bold text-[#061018] shadow-[0_14px_36px_rgba(14,165,233,0.18)] transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
                            >
                                {isCheckingOut && <Spinner className="h-4 w-4" />}
                                {!isAuthenticated
                                    ? t('creditPurchaseSignIn')
                                    : selectedPackage
                                        ? t('creditPurchaseContinueToPayment', {
                                            amount: (selectedPackage.amount_eur_cents / 100).toFixed(2),
                                        })
                                        : t('creditPurchaseContinue')}
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

function PackageOption({
    creditPackage,
    packageLabel,
    selected,
    onSelect,
    onKeyDown,
    inputRef,
    creditsLabel,
}: {
    creditPackage: CreditPackage;
    packageLabel: string;
    selected: boolean;
    onSelect: () => void;
    onKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void;
    inputRef: (element: HTMLInputElement | null) => void;
    creditsLabel: string;
}) {
    return (
        <label className="block cursor-pointer">
            <input
                ref={inputRef}
                type="radio"
                name="credit-package"
                value={creditPackage.key}
                checked={selected}
                onChange={onSelect}
                onKeyDown={onKeyDown}
                className="peer sr-only"
            />
            <span
                className={`relative block min-h-36 rounded-2xl border p-3.5 text-left transition sm:p-4 peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-sky-300 peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-[#0a0b0e] ${
                    selected
                        ? 'border-sky-400 bg-sky-400/[0.09] shadow-[0_0_0_1px_rgba(56,189,248,0.25)]'
                        : 'border-white/10 bg-white/[0.025] hover:border-white/20 hover:bg-white/[0.045]'
                }`}
            >
                <span className="block truncate text-[10px] font-bold uppercase tracking-[0.16em] text-[#8d96a3] sm:text-xs">
                    {packageLabel}
                </span>
                <strong className="mt-5 block text-2xl tracking-[-0.05em] sm:text-3xl">
                    €{(creditPackage.amount_eur_cents / 100).toFixed(2)}
                </strong>
                <span className="mt-3 flex items-center gap-1.5 text-[11px] font-medium text-[#cbd3dc] sm:text-sm">
                    <CoinsIcon className="hidden h-3.5 w-3.5 text-sky-300 sm:block" />
                    {formatPoints(creditPackage.credits)} {creditsLabel}
                </span>
            </span>
        </label>
    );
}
