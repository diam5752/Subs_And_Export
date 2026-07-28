'use client';

import Link from 'next/link';
import {
    FormEvent,
    useCallback,
    useEffect,
    useRef,
    useState,
} from 'react';
import { BrandLogo } from '@/components/BrandLogo';
import { Spinner } from '@/components/Spinner';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';
import {
    api,
    type BillingPurchaseResponse,
} from '@/lib/api';
import { paidCreditLegalPublicationIsApproved } from '@/lib/paidCreditLegal';

function withdrawalIdempotencyKey(): string {
    const random = typeof crypto !== 'undefined'
        && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `withdrawal-${random}`;
}

function downloadBlob(blob: Blob, filename: string): void {
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.URL.revokeObjectURL(url);
}

export default function BillingAccountPage() {
    const { user, isLoading: authLoading } = useAuth();
    const { locale, t } = useI18n();
    const [purchases, setPurchases] = useState<BillingPurchaseResponse[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [selectedPurchaseId, setSelectedPurchaseId] = useState<string | null>(null);
    const [confirmedName, setConfirmedName] = useState('');
    const [confirmationEmail, setConfirmationEmail] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const withdrawalKeyRef = useRef(withdrawalIdempotencyKey());
    const withdrawalNameInputRef = useRef<HTMLInputElement>(null);
    const withdrawalStartButtonsRef = useRef(
        new Map<string, HTMLButtonElement>(),
    );
    const restoreStartFocusForRef = useRef<string | null>(null);
    const focusSuccessNoticeRef = useRef(false);
    const noticeRef = useRef<HTMLParagraphElement>(null);

    const loadPurchases = useCallback(async () => {
        if (!user) {
            setPurchases([]);
            setLoading(false);
            return;
        }
        setLoading(true);
        setError('');
        try {
            setPurchases(await api.listBillingPurchases());
        } catch (loadError) {
            setError(
                loadError instanceof Error
                    ? loadError.message
                    : t('billingPageLoadError'),
            );
        } finally {
            setLoading(false);
        }
    }, [t, user]);

    useEffect(() => {
        if (authLoading) return;
        const loadTimer = window.setTimeout(() => {
            void loadPurchases();
        }, 0);
        return () => window.clearTimeout(loadTimer);
    }, [authLoading, loadPurchases]);

    useEffect(() => {
        if (selectedPurchaseId) {
            queueMicrotask(() => withdrawalNameInputRef.current?.focus());
            return;
        }
        const purchaseId = restoreStartFocusForRef.current;
        if (!purchaseId) return;
        restoreStartFocusForRef.current = null;
        queueMicrotask(() => {
            withdrawalStartButtonsRef.current.get(purchaseId)?.focus();
        });
    }, [selectedPurchaseId]);

    useEffect(() => {
        if (!notice || !focusSuccessNoticeRef.current) return;
        focusSuccessNoticeRef.current = false;
        queueMicrotask(() => noticeRef.current?.focus());
    }, [notice]);

    const beginWithdrawal = (purchaseId: string) => {
        if (!user) return;
        setSelectedPurchaseId(purchaseId);
        setConfirmedName(user.name);
        setConfirmationEmail(user.email);
        setError('');
        setNotice('');
        withdrawalKeyRef.current = withdrawalIdempotencyKey();
    };

    const submitWithdrawal = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!selectedPurchaseId) return;
        setSubmitting(true);
        setError('');
        setNotice('');
        try {
            await api.submitBillingWithdrawal(
                selectedPurchaseId,
                {
                    locale,
                    withdrawal_requested: true,
                    confirmed_name: confirmedName,
                    confirmation_email: confirmationEmail,
                },
                withdrawalKeyRef.current,
            );
            focusSuccessNoticeRef.current = true;
            setSelectedPurchaseId(null);
            setNotice(t('billingWithdrawalPending'));
            await loadPurchases();
        } catch (submitError) {
            setError(
                submitError instanceof Error
                    ? submitError.message
                    : t('billingWithdrawalError'),
            );
        } finally {
            setSubmitting(false);
        }
    };

    const downloadArtifact = async (
        endpoint: string | null,
        filename: string,
    ) => {
        if (!endpoint) return;
        setError('');
        try {
            const artifact = await api.downloadBillingArtifact(endpoint);
            downloadBlob(artifact, filename);
        } catch (downloadError) {
            setError(
                downloadError instanceof Error
                    ? downloadError.message
                    : t('billingArtifactError'),
            );
        }
    };

    return (
        <div className="min-h-dvh bg-[#f7f7f5] text-[var(--foreground)]">
            <header className="border-b border-[#e7e7e5] bg-[#f7f7f5]">
                <div className="mx-auto flex min-h-[72px] w-full max-w-5xl items-center justify-between gap-4 px-5 sm:px-8">
                    <Link href="/" aria-label={t('brandHomeLabel')}>
                        <BrandLogo className="block h-auto w-[132px] sm:w-[164px]" />
                    </Link>
                    <Link
                        href="/"
                        className="text-sm font-semibold text-[var(--muted)] hover:text-[var(--foreground)]"
                    >
                        {t('billingPageBack')}
                    </Link>
                </div>
            </header>

            <main className="mx-auto w-full max-w-4xl px-5 py-10 sm:px-8 sm:py-16">
                <p className="text-xs font-bold tracking-[0.18em] text-[var(--accent)]">
                    {t('billingPageKicker')}
                </p>
                <h1 className="mt-3 text-4xl font-extrabold tracking-[-0.045em] sm:text-5xl">
                    {t('billingPageTitle')}
                </h1>
                <p className="mt-4 max-w-2xl text-base leading-7 text-[var(--muted)]">
                    {t('billingPageDescription')}
                </p>

                {error && (
                    <p role="alert" className="mt-6 rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-800">
                        {error}
                    </p>
                )}
                {notice && (
                    <p
                        ref={noticeRef}
                        role="status"
                        tabIndex={-1}
                        className="mt-6 rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                    >
                        {notice}
                    </p>
                )}

                {authLoading || loading ? (
                    <div className="grid min-h-52 place-items-center">
                        <Spinner className="h-6 w-6" />
                    </div>
                ) : !user ? (
                    <div className="mt-8 rounded-2xl border border-[var(--border)] bg-white p-6">
                        <p>{t('billingPageSignIn')}</p>
                        <Link href="/login" className="mt-4 inline-flex font-semibold text-[var(--accent)] underline">
                            {t('loginSubmit')}
                        </Link>
                    </div>
                ) : purchases.length === 0 ? (
                    <p className="mt-8 rounded-2xl border border-[var(--border)] bg-white p-6">
                        {t('billingPageEmpty')}
                    </p>
                ) : (
                    <div className="mt-8 space-y-5">
                        {purchases.map((purchase) => (
                            <article
                                key={purchase.purchase_id}
                                className="rounded-2xl border border-[var(--border)] bg-white p-5 shadow-sm sm:p-6"
                            >
                                <div className="flex flex-wrap items-start justify-between gap-4">
                                    <div>
                                        <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted)]">
                                            {purchase.package_key}
                                        </p>
                                        <h2 className="mt-2 text-xl font-bold">
                                            €{(purchase.amount_eur_cents / 100).toFixed(2)}
                                            {' · '}
                                            {purchase.credits} credits
                                        </h2>
                                        <p className="mt-2 text-sm text-[var(--muted)]">
                                            {new Date(purchase.created_at * 1000).toLocaleString(locale)}
                                            {' · '}
                                            {purchase.status}
                                        </p>
                                    </div>
                                    {purchase.contract_confirmation_url && (
                                        <button
                                            type="button"
                                            onClick={() => void downloadArtifact(
                                                purchase.contract_confirmation_url,
                                                `gsubs-contract-${purchase.purchase_id}.json`,
                                            )}
                                            className="min-h-11 rounded-xl border border-[var(--border)] px-4 text-sm font-semibold hover:bg-black/[0.03]"
                                        >
                                            {t('billingContractDownload')}
                                        </button>
                                    )}
                                </div>

                                <div className="mt-5 border-t border-[var(--border)] pt-5">
                                    {purchase.withdrawal_resolution_available ? (
                                        <div className="space-y-3">
                                            <p
                                                className={`rounded-xl border p-4 text-sm font-semibold leading-6 ${
                                                    purchase.withdrawal_resolution_decision
                                                    === 'accepted_refunded'
                                                        ? 'border-emerald-300 bg-emerald-50 text-emerald-950'
                                                        : 'border-amber-300 bg-amber-50 text-amber-950'
                                                }`}
                                            >
                                                {t(
                                                    purchase.withdrawal_resolution_decision
                                                    === 'accepted_refunded'
                                                        ? 'billingWithdrawalAccepted'
                                                        : 'billingWithdrawalRejected',
                                                )}
                                            </p>
                                            <div className="flex flex-wrap gap-3">
                                                {purchase.withdrawal_acknowledgement_url && (
                                                    <button
                                                        type="button"
                                                        onClick={() => void downloadArtifact(
                                                            purchase.withdrawal_acknowledgement_url,
                                                            `gsubs-withdrawal-${purchase.purchase_id}.json`,
                                                        )}
                                                        className="min-h-11 rounded-xl border border-[var(--border)] px-4 text-sm font-semibold hover:bg-black/[0.03]"
                                                    >
                                                        {t('billingWithdrawalDownload')}
                                                    </button>
                                                )}
                                                {purchase.withdrawal_resolution_url && (
                                                    <button
                                                        type="button"
                                                        onClick={() => void downloadArtifact(
                                                            purchase.withdrawal_resolution_url,
                                                            `gsubs-withdrawal-resolution-${purchase.purchase_id}.json`,
                                                        )}
                                                        className="min-h-11 rounded-xl border border-[var(--border)] px-4 text-sm font-semibold hover:bg-black/[0.03]"
                                                    >
                                                        {t('billingWithdrawalResolutionDownload')}
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    ) : purchase.withdrawal_status ? (
                                        <div className="space-y-3">
                                            <p className="text-sm leading-6 text-amber-800">
                                                {t('billingWithdrawalPending')}
                                            </p>
                                            {purchase.withdrawal_acknowledgement_url && (
                                                <button
                                                    type="button"
                                                    onClick={() => void downloadArtifact(
                                                        purchase.withdrawal_acknowledgement_url,
                                                        `gsubs-withdrawal-${purchase.purchase_id}.json`,
                                                    )}
                                                    className="min-h-11 rounded-xl border border-[var(--border)] px-4 text-sm font-semibold hover:bg-black/[0.03]"
                                                >
                                                    {t('billingWithdrawalDownload')}
                                                </button>
                                            )}
                                        </div>
                                    ) : purchase.withdrawal_action_available ? (
                                        selectedPurchaseId === purchase.purchase_id ? (
                                            <form className="space-y-4" onSubmit={submitWithdrawal}>
                                                <h3 className="font-bold">
                                                    {t('billingWithdrawalConfirmTitle')}
                                                </h3>
                                                <div className="space-y-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-950">
                                                    <p className="font-semibold">
                                                        {t('billingWithdrawalStatement', {
                                                            purchaseId: purchase.purchase_id,
                                                        })}
                                                    </p>
                                                    <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
                                                        <dt>{t('billingWithdrawalPurchaseId')}</dt>
                                                        <dd className="break-all font-mono">
                                                            {purchase.purchase_id}
                                                        </dd>
                                                        <dt>{t('billingWithdrawalPackage')}</dt>
                                                        <dd>{purchase.package_key}</dd>
                                                        <dt>{t('billingWithdrawalConcludedAt')}</dt>
                                                        <dd>
                                                            {purchase.contract_concluded_at === null
                                                                ? '—'
                                                                : new Date(
                                                                    purchase.contract_concluded_at * 1000,
                                                                ).toLocaleString(locale)}
                                                        </dd>
                                                    </dl>
                                                </div>
                                                <div>
                                                    <label className="mb-2 block text-sm font-medium" htmlFor={`withdrawal-name-${purchase.purchase_id}`}>
                                                        {t('billingWithdrawalName')}
                                                    </label>
                                                    <input
                                                        ref={withdrawalNameInputRef}
                                                        id={`withdrawal-name-${purchase.purchase_id}`}
                                                        value={confirmedName}
                                                        onChange={(event) => setConfirmedName(event.target.value)}
                                                        required
                                                        maxLength={100}
                                                        className="input-field"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="mb-2 block text-sm font-medium" htmlFor={`withdrawal-email-${purchase.purchase_id}`}>
                                                        {t('billingWithdrawalEmail')}
                                                    </label>
                                                    <input
                                                        id={`withdrawal-email-${purchase.purchase_id}`}
                                                        type="email"
                                                        value={confirmationEmail}
                                                        onChange={(event) => setConfirmationEmail(event.target.value)}
                                                        required
                                                        maxLength={255}
                                                        className="input-field"
                                                    />
                                                </div>
                                                <div className="flex flex-wrap gap-3">
                                                    <button
                                                        type="submit"
                                                        disabled={submitting}
                                                        className="btn-primary min-h-11"
                                                    >
                                                        {submitting && <Spinner className="mr-2 h-4 w-4" />}
                                                        {t('billingWithdrawalConfirm')}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        disabled={submitting}
                                                        onClick={() => {
                                                            restoreStartFocusForRef.current = (
                                                                purchase.purchase_id
                                                            );
                                                            setSelectedPurchaseId(null);
                                                        }}
                                                        className="min-h-11 rounded-xl border border-[var(--border)] px-4 font-semibold"
                                                    >
                                                        {t('billingWithdrawalCancel')}
                                                    </button>
                                                </div>
                                            </form>
                                        ) : (
                                            <button
                                                ref={(element) => {
                                                    if (element) {
                                                        withdrawalStartButtonsRef.current.set(
                                                            purchase.purchase_id,
                                                            element,
                                                        );
                                                    } else {
                                                        withdrawalStartButtonsRef.current.delete(
                                                            purchase.purchase_id,
                                                        );
                                                    }
                                                }}
                                                type="button"
                                                onClick={() => beginWithdrawal(purchase.purchase_id)}
                                                className="min-h-11 rounded-xl border border-red-300 px-4 text-sm font-bold text-red-700 hover:bg-red-50"
                                            >
                                                {t('billingWithdrawalStart')}
                                            </button>
                                        )
                                    ) : (
                                        <p className="text-sm leading-6 text-[var(--muted)]">
                                            {t(
                                                !purchase.contract_confirmation_available
                                                || purchase.contract_concluded_at === null
                                                    ? 'billingContractNotConcluded'
                                                    : 'billingWithdrawalUnavailable',
                                            )}
                                        </p>
                                    )}
                                </div>
                            </article>
                        ))}
                    </div>
                )}

                {paidCreditLegalPublicationIsApproved() && (
                    <Link
                        href="/terms#withdrawal"
                        className="mt-8 inline-flex text-sm font-semibold text-[var(--accent)] underline"
                    >
                        {t('creditPurchaseWithdrawalFormLink')}
                    </Link>
                )}
            </main>
        </div>
    );
}
