'use client';

import Link from 'next/link';
import {
    useCallback,
    useEffect,
    useState,
} from 'react';
import { useForm } from 'react-hook-form';
import { BrandLogo } from '@/components/BrandLogo';
import { Spinner } from '@/components/Spinner';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';
import {
    ApiError,
    api,
    type BillingAdminPendingInvoice,
    type RecordedAadeDocumentResponse,
} from '@/lib/api';
import {
    AADE_GREEK_B2C_DOCUMENT_TYPE,
    AADE_GREEK_B2C_SERIES,
    ATHENS_TIME_ZONE,
    currentEpochSeconds,
    currentMinuteEpochSeconds,
    isCanonicalAadeMark,
    parseAthensDateTime,
    toAthensDateTimeValue,
} from '@/lib/billingAdmin';

type DocumentFormValues = {
    documentType: string;
    series: string;
    aa: string;
    mark: string;
    markRepeat: string;
    issuedAt: string;
    finalDocumentConfirmed: boolean;
};

type InvoiceCardProps = {
    invoice: BillingAdminPendingInvoice;
    onRecorded: (record: RecordedAadeDocumentResponse) => void;
};

function formattedMoney(
    amountCents: number | null,
    currency: string | null,
    locale: string,
): string {
    if (amountCents === null || !currency) {
        return '—';
    }
    return new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: currency.toUpperCase(),
    }).format(amountCents / 100);
}

function formattedDateTime(epochSeconds: number | null, locale: string): string {
    if (epochSeconds === null) {
        return '—';
    }
    return new Intl.DateTimeFormat(locale, {
        timeZone: ATHENS_TIME_ZONE,
        dateStyle: 'medium',
        timeStyle: 'medium',
    }).format(new Date(epochSeconds * 1000));
}

function identifier(value: string | null): React.ReactNode {
    return value
        ? <code className="break-all text-xs font-semibold text-[var(--foreground)]">{value}</code>
        : <span aria-label="missing">—</span>;
}

function LabeledValue({
    label,
    children,
}: {
    label: string;
    children: React.ReactNode;
}) {
    return (
        <div className="min-w-0">
            <dt className="text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--muted)]">
                {label}
            </dt>
            <dd className="mt-1 break-words text-sm text-[var(--foreground)]">
                {children}
            </dd>
        </div>
    );
}

function BillingInvoiceCard({
    invoice,
    onRecorded,
}: InvoiceCardProps) {
    const { locale, t } = useI18n();
    const [recordError, setRecordError] = useState('');
    const paymentConfirmedAt = invoice.payment?.confirmed_at ?? null;
    const livemode = invoice.payment?.livemode ?? null;
    const currency = invoice.payment?.currency ?? null;
    const grossCents = invoice.tax.gross_amount_cents;
    const netCents = invoice.tax.net_amount_cents;
    const vatCents = invoice.tax.vat_amount_cents;
    const vatRate = invoice.tax.vat_rate_percent;
    const missingCustomerFields = invoice.customer?.missing_required_fields ?? [];
    const customerAddress = [
        invoice.customer?.line1,
        invoice.customer?.line2,
        [
            invoice.customer?.postal_code,
            invoice.customer?.city,
        ].filter(Boolean).join(' '),
        invoice.customer?.country,
    ].filter(Boolean).join(', ');
    const isIssued = invoice.aade_mark !== null
        || invoice.document_status === 'issued'
        || invoice.document_status === 'cancelled';
    const cannotRecord = invoice.requires_reversal_review
        || isIssued
        || paymentConfirmedAt === null;
    const {
        formState: { errors, isSubmitting },
        getValues,
        handleSubmit,
        register,
        setValue,
    } = useForm<DocumentFormValues>({
        defaultValues: {
            documentType: AADE_GREEK_B2C_DOCUMENT_TYPE,
            series: AADE_GREEK_B2C_SERIES,
            aa: '',
            mark: '',
            markRepeat: '',
            issuedAt: '',
            finalDocumentConfirmed: false,
        },
    });

    useEffect(() => {
        setValue(
            'issuedAt',
            toAthensDateTimeValue(currentMinuteEpochSeconds()),
        );
    }, [setValue]);

    const submitDocument = handleSubmit(async (values) => {
        if (cannotRecord) {
            return;
        }
        const issuedAt = parseAthensDateTime(values.issuedAt);
        if (issuedAt === null) {
            return;
        }
        setRecordError('');
        try {
            const record = await api.recordIssuedAadeDocument(
                invoice.invoice_id,
                {
                    document_type: values.documentType.trim(),
                    series: values.series.trim(),
                    aa: values.aa,
                    mark: values.mark,
                    issued_at: issuedAt,
                },
            );
            onRecorded(record);
        } catch (error) {
            // This write is deliberately never retried automatically. A lost
            // response must be reconciled by refreshing the server queue.
            setRecordError(
                error instanceof ApiError && error.status === 403
                    ? t('adminBillingRecentSignInRequired')
                    : t('adminBillingRecordError'),
            );
        }
    });

    const statusLabel = invoice.document_status === 'manual_review_required'
        ? t('adminBillingManualReviewStatus')
        : t('adminBillingPendingStatus');

    return (
        <article
            className="overflow-hidden rounded-3xl border border-[var(--border)] bg-white shadow-sm"
            data-testid={`billing-admin-invoice-${invoice.invoice_id}`}
        >
            <div className="border-b border-[var(--border)] bg-[#fafaf8] p-5 sm:p-7">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-900">
                                {statusLabel}
                            </span>
                            {livemode !== null && (
                                <span className={`rounded-full px-3 py-1 text-xs font-bold ${
                                    livemode
                                        ? 'bg-red-100 text-red-900'
                                        : 'bg-sky-100 text-sky-900'
                                }`}>
                                    {livemode
                                        ? t('adminBillingLiveMode')
                                        : t('adminBillingTestMode')}
                                </span>
                            )}
                        </div>
                        <h2 className="mt-4 text-2xl font-extrabold tracking-[-0.03em]">
                            {invoice.service.name ?? 'GSUBS Credits'}
                        </h2>
                        <p className="mt-1 text-sm text-[var(--muted)]">
                            {invoice.package.key ?? '—'}
                            {' · '}
                            {invoice.package.credits ?? '—'} {t('adminBillingCredits')}
                        </p>
                    </div>
                    <div className="text-right">
                        <p className="text-2xl font-extrabold">
                            {formattedMoney(grossCents, currency, locale)}
                        </p>
                        <p className="mt-1 text-xs text-[var(--muted)]">
                            {t('adminBillingNet')} {formattedMoney(netCents, currency, locale)}
                            {' · '}
                            {t('adminBillingVat')} {vatRate ?? '—'}%: {formattedMoney(vatCents, currency, locale)}
                        </p>
                    </div>
                </div>
            </div>

            <div className="grid gap-7 p-5 sm:p-7 lg:grid-cols-2">
                <section aria-labelledby={`payment-${invoice.invoice_id}`}>
                    <h3
                        id={`payment-${invoice.invoice_id}`}
                        className="text-base font-extrabold"
                    >
                        {t('adminBillingPaymentTitle')}
                    </h3>
                    <dl className="mt-4 grid gap-4">
                        <LabeledValue label={t('adminBillingPurchaseId')}>
                            {identifier(invoice.purchase_id)}
                        </LabeledValue>
                        <LabeledValue label={t('adminBillingInvoiceId')}>
                            {identifier(invoice.invoice_id)}
                        </LabeledValue>
                        <LabeledValue label={t('adminBillingCheckoutId')}>
                            {identifier(invoice.payment?.checkout_session_id ?? null)}
                        </LabeledValue>
                        <LabeledValue label={t('adminBillingPaymentIntentId')}>
                            {identifier(invoice.payment?.payment_intent_id ?? null)}
                        </LabeledValue>
                        <LabeledValue label={t('adminBillingPaymentConfirmed')}>
                            {formattedDateTime(paymentConfirmedAt, locale)}
                            {' '}
                            <span className="text-xs text-[var(--muted)]">
                                ({ATHENS_TIME_ZONE})
                            </span>
                        </LabeledValue>
                    </dl>
                </section>

                <section aria-labelledby={`customer-${invoice.invoice_id}`}>
                    <h3
                        id={`customer-${invoice.invoice_id}`}
                        className="text-base font-extrabold"
                    >
                        {t('adminBillingCustomerTitle')}
                    </h3>
                    <dl className="mt-4 grid gap-4">
                        <LabeledValue label={t('adminBillingService')}>
                            {invoice.service.code ?? '—'}
                            {' · '}
                            {invoice.service.name ?? '—'}
                        </LabeledValue>
                        <LabeledValue label={t('adminBillingCustomerName')}>
                            {invoice.customer?.name ?? '—'}
                        </LabeledValue>
                        <LabeledValue label={t('adminBillingCustomerEmail')}>
                            {invoice.customer?.email ?? '—'}
                        </LabeledValue>
                        <LabeledValue label={t('adminBillingCustomerAddress')}>
                            {customerAddress || '—'}
                        </LabeledValue>
                        {missingCustomerFields.length > 0 && (
                            <LabeledValue label={t('adminBillingMissingFields')}>
                                <span className="font-semibold text-amber-800">
                                    {missingCustomerFields.join(', ')}
                                </span>
                            </LabeledValue>
                        )}
                    </dl>
                </section>
            </div>

            <div className="border-t border-[var(--border)] bg-[#fcfcfb] p-5 sm:p-7">
                {invoice.requires_reversal_review ? (
                    <p
                        role="alert"
                        className="rounded-2xl border border-red-300 bg-red-50 p-4 text-sm font-semibold leading-6 text-red-900"
                    >
                        {t('adminBillingReversalWarning')}
                    </p>
                ) : isIssued ? (
                    <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4">
                        <p className="text-sm font-semibold leading-6 text-amber-950">
                            {t('adminBillingIssuedReview')}
                        </p>
                        <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                            <LabeledValue label={t('adminBillingDocumentType')}>
                                {invoice.aade_document_type ?? '—'}
                            </LabeledValue>
                            <LabeledValue label={t('adminBillingSeries')}>
                                {invoice.aade_series ?? '—'}
                            </LabeledValue>
                            <LabeledValue label={t('adminBillingAa')}>
                                {invoice.aade_aa ?? '—'}
                            </LabeledValue>
                            <LabeledValue label={t('adminBillingMark')}>
                                {identifier(invoice.aade_mark)}
                            </LabeledValue>
                            <LabeledValue label={t('adminBillingIssuedAt')}>
                                {formattedDateTime(invoice.issued_at, locale)}
                            </LabeledValue>
                        </dl>
                    </div>
                ) : paymentConfirmedAt === null ? (
                    <p
                        role="alert"
                        className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm font-semibold leading-6 text-amber-950"
                    >
                        {t('adminBillingManualReviewStatus')}: {t('adminBillingBeforePayment')}
                    </p>
                ) : (
                    <form
                        className="space-y-5"
                        onSubmit={(event) => void submitDocument(event)}
                        noValidate
                    >
                        <div>
                            <h3 className="text-lg font-extrabold">
                                {t('adminBillingDocumentTitle')}
                            </h3>
                            <p className="mt-2 max-w-4xl text-sm leading-6 text-[var(--muted)]">
                                {t('adminBillingImmutableWarning')}
                            </p>
                            <p className="mt-2 max-w-4xl text-sm font-semibold leading-6 text-[var(--foreground)]">
                                {t('adminBillingMizaiBaseline')}
                            </p>
                        </div>

                        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                            <label className="grid gap-2 text-sm font-semibold">
                                {t('adminBillingDocumentType')}
                                <input
                                    className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3"
                                    autoComplete="off"
                                    inputMode="decimal"
                                    readOnly
                                    aria-readonly="true"
                                    {...register('documentType', {
                                        required: t('adminBillingInvalidDocumentType'),
                                        validate: (value) => (
                                            value === AADE_GREEK_B2C_DOCUMENT_TYPE
                                            || t('adminBillingInvalidDocumentType')
                                        ),
                                    })}
                                />
                                {errors.documentType && (
                                    <span role="alert" className="text-xs text-red-700">
                                        {errors.documentType.message}
                                    </span>
                                )}
                            </label>

                            <label className="grid gap-2 text-sm font-semibold">
                                {t('adminBillingSeries')}
                                <input
                                    className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3"
                                    autoComplete="off"
                                    readOnly
                                    aria-readonly="true"
                                    {...register('series', {
                                        required: t('adminBillingInvalidSeries'),
                                        validate: (value) => (
                                            value === AADE_GREEK_B2C_SERIES
                                            || t('adminBillingInvalidSeries')
                                        ),
                                    })}
                                />
                                {errors.series && (
                                    <span role="alert" className="text-xs text-red-700">
                                        {errors.series.message}
                                    </span>
                                )}
                            </label>

                            <label className="grid gap-2 text-sm font-semibold">
                                {t('adminBillingAa')}
                                <input
                                    className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3"
                                    autoComplete="off"
                                    inputMode="numeric"
                                    {...register('aa', {
                                        required: t('adminBillingInvalidAa'),
                                        maxLength: {
                                            value: 64,
                                            message: t('adminBillingInvalidAa'),
                                        },
                                        pattern: {
                                            value: /^[0-9]+$/,
                                            message: t('adminBillingInvalidAa'),
                                        },
                                    })}
                                />
                                {errors.aa && (
                                    <span role="alert" className="text-xs text-red-700">
                                        {errors.aa.message}
                                    </span>
                                )}
                            </label>

                            <label className="grid gap-2 text-sm font-semibold">
                                {t('adminBillingMark')}
                                <input
                                    className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3 font-mono"
                                    autoComplete="off"
                                    inputMode="numeric"
                                    {...register('mark', {
                                        required: t('adminBillingInvalidMark'),
                                        validate: (value) => (
                                            isCanonicalAadeMark(value)
                                            || t('adminBillingInvalidMark')
                                        ),
                                    })}
                                />
                                {errors.mark && (
                                    <span role="alert" className="text-xs text-red-700">
                                        {errors.mark.message}
                                    </span>
                                )}
                            </label>

                            <label className="grid gap-2 text-sm font-semibold">
                                {t('adminBillingMarkRepeat')}
                                <input
                                    className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3 font-mono"
                                    autoComplete="off"
                                    inputMode="numeric"
                                    {...register('markRepeat', {
                                        required: t('adminBillingMarkMismatch'),
                                        validate: (value) => (
                                            value === getValues('mark')
                                            || t('adminBillingMarkMismatch')
                                        ),
                                    })}
                                />
                                {errors.markRepeat && (
                                    <span role="alert" className="text-xs text-red-700">
                                        {errors.markRepeat.message}
                                    </span>
                                )}
                            </label>

                            <label className="grid gap-2 text-sm font-semibold">
                                {t('adminBillingIssuedAt')}
                                <input
                                    type="datetime-local"
                                    step="60"
                                    className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3"
                                    {...register('issuedAt', {
                                        required: t('adminBillingInvalidIssuedAt'),
                                        validate: (value) => {
                                            const issuedAt = parseAthensDateTime(value);
                                            if (issuedAt === null) {
                                                return t('adminBillingInvalidIssuedAt');
                                            }
                                            if (issuedAt > currentEpochSeconds()) {
                                                return t('adminBillingFutureIssuedAt');
                                            }
                                            if (issuedAt < paymentConfirmedAt) {
                                                return t('adminBillingBeforePayment');
                                            }
                                            return true;
                                        },
                                    })}
                                />
                                <span className="text-xs font-normal leading-5 text-[var(--muted)]">
                                    {t('adminBillingAthensTimeHelp')}
                                </span>
                                {errors.issuedAt && (
                                    <span role="alert" className="text-xs text-red-700">
                                        {errors.issuedAt.message}
                                    </span>
                                )}
                            </label>
                        </div>

                        <label className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-white p-4 text-sm font-semibold leading-6">
                            <input
                                type="checkbox"
                                className="mt-1 h-5 w-5 shrink-0 accent-[var(--accent)]"
                                {...register('finalDocumentConfirmed', {
                                    required: t('adminBillingFinalDocumentConfirm'),
                                })}
                            />
                            <span>{t('adminBillingFinalDocumentConfirm')}</span>
                        </label>
                        {errors.finalDocumentConfirmed && (
                            <p role="alert" className="text-sm text-red-700">
                                {errors.finalDocumentConfirmed.message}
                            </p>
                        )}

                        {recordError && (
                            <p
                                role="alert"
                                className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900"
                            >
                                {recordError}
                            </p>
                        )}

                        <button
                            type="submit"
                            disabled={isSubmitting}
                            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[var(--foreground)] px-5 font-bold text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {isSubmitting && <Spinner className="h-4 w-4" />}
                            {isSubmitting
                                ? t('adminBillingRecording')
                                : t('adminBillingRecord')}
                        </button>
                    </form>
                )}
            </div>
        </article>
    );
}

export default function BillingAdminPage() {
    const { user, isLoading: authLoading } = useAuth();
    const { t } = useI18n();
    const [items, setItems] = useState<BillingAdminPendingInvoice[]>([]);
    const [nextCursor, setNextCursor] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [accessDenied, setAccessDenied] = useState(false);
    const [loadError, setLoadError] = useState('');
    const [notice, setNotice] = useState('');

    const loadInvoices = useCallback(async ({
        after = null,
        append = false,
    }: {
        after?: string | null;
        append?: boolean;
    } = {}) => {
        if (!user) {
            setItems([]);
            setNextCursor(null);
            setLoading(false);
            return;
        }
        if (append) {
            setLoadingMore(true);
        } else {
            setLoading(true);
            setAccessDenied(false);
            setLoadError('');
        }
        try {
            const response = await api.listPendingBillingInvoices(
                after ?? undefined,
            );
            setItems((current) => {
                if (!append) {
                    return response.items;
                }
                const existing = new Set(current.map((item) => item.invoice_id));
                return [
                    ...current,
                    ...response.items.filter((item) => !existing.has(item.invoice_id)),
                ];
            });
            setNextCursor(response.next_cursor);
        } catch (error) {
            if (error instanceof ApiError && error.status === 403) {
                setAccessDenied(true);
            } else {
                setLoadError(t('adminBillingLoadError'));
            }
        } finally {
            setLoading(false);
            setLoadingMore(false);
        }
    }, [t, user]);

    useEffect(() => {
        if (authLoading) {
            return;
        }
        const timer = window.setTimeout(() => {
            void loadInvoices();
        }, 0);
        return () => window.clearTimeout(timer);
    }, [authLoading, loadInvoices]);

    const handleRecorded = useCallback(
        (record: RecordedAadeDocumentResponse) => {
            setItems((current) => current.filter(
                (item) => item.invoice_id !== record.invoice_id,
            ));
            setNotice(t('adminBillingRecorded', { mark: record.aade_mark }));
        },
        [t],
    );

    const refresh = useCallback(() => {
        setNotice('');
        void loadInvoices();
    }, [loadInvoices]);

    return (
        <div className="min-h-dvh bg-[#f4f4f1] text-[var(--foreground)]">
            <header className="border-b border-[#deded9] bg-[#f7f7f5]">
                <div className="mx-auto flex min-h-[72px] w-full max-w-6xl items-center justify-between gap-4 px-5 sm:px-8">
                    <Link href="/" aria-label={t('brandHomeLabel')}>
                        <BrandLogo className="block h-auto w-[132px] sm:w-[164px]" />
                    </Link>
                    <Link
                        href="/"
                        className="text-sm font-semibold text-[var(--muted)] hover:text-[var(--foreground)]"
                    >
                        {t('adminBillingBack')}
                    </Link>
                </div>
            </header>

            <main className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 sm:py-16">
                <p className="text-xs font-extrabold tracking-[0.18em] text-[var(--accent)]">
                    {t('adminBillingKicker')}
                </p>
                <h1 className="mt-3 text-4xl font-extrabold tracking-[-0.045em] sm:text-6xl">
                    {t('adminBillingTitle')}
                </h1>
                <p className="mt-4 max-w-3xl text-base leading-7 text-[var(--muted)]">
                    {t('adminBillingDescription')}
                </p>
                <p className="mt-4 max-w-3xl rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm leading-6 text-sky-950">
                    {t('adminBillingPrivacyNotice')}
                </p>

                {notice && (
                    <p
                        role="status"
                        className="mt-6 rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm font-semibold text-emerald-950"
                    >
                        {notice}
                    </p>
                )}

                {authLoading || loading ? (
                    <div className="grid min-h-64 place-items-center">
                        <div className="flex items-center gap-3 text-sm font-semibold text-[var(--muted)]">
                            <Spinner className="h-5 w-5" />
                            {t('adminBillingLoading')}
                        </div>
                    </div>
                ) : !user ? (
                    <div className="mt-8 rounded-2xl border border-[var(--border)] bg-white p-6">
                        <p>{t('adminBillingSignIn')}</p>
                        <Link
                            href="/login"
                            className="mt-4 inline-flex min-h-11 items-center font-bold text-[var(--accent)] underline"
                        >
                            {t('loginSubmit')}
                        </Link>
                    </div>
                ) : accessDenied ? (
                    <p
                        role="alert"
                        className="mt-8 rounded-2xl border border-red-300 bg-red-50 p-6 text-red-900"
                    >
                        {t('adminBillingForbidden')}
                    </p>
                ) : loadError ? (
                    <div className="mt-8 rounded-2xl border border-red-300 bg-red-50 p-6">
                        <p role="alert" className="text-red-900">{loadError}</p>
                        <button
                            type="button"
                            onClick={refresh}
                            className="mt-4 min-h-11 rounded-xl border border-red-400 px-4 font-bold text-red-900"
                        >
                            {t('adminBillingRefresh')}
                        </button>
                    </div>
                ) : items.length === 0 ? (
                    <div className="mt-8 rounded-2xl border border-[var(--border)] bg-white p-6">
                        <p>{t('adminBillingEmpty')}</p>
                        <button
                            type="button"
                            onClick={refresh}
                            className="mt-4 min-h-11 rounded-xl border border-[var(--border-strong)] px-4 font-bold"
                        >
                            {t('adminBillingRefresh')}
                        </button>
                    </div>
                ) : (
                    <>
                        <div className="mt-8 space-y-6">
                            {items.map((invoice) => (
                                <BillingInvoiceCard
                                    key={invoice.invoice_id}
                                    invoice={invoice}
                                    onRecorded={handleRecorded}
                                />
                            ))}
                        </div>
                        <div className="mt-8 flex flex-wrap gap-3">
                            <button
                                type="button"
                                onClick={refresh}
                                className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-4 font-bold"
                            >
                                {t('adminBillingRefresh')}
                            </button>
                            {nextCursor && (
                                <button
                                    type="button"
                                    disabled={loadingMore}
                                    onClick={() => void loadInvoices({
                                        after: nextCursor,
                                        append: true,
                                    })}
                                    className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[var(--foreground)] px-4 font-bold text-white disabled:opacity-60"
                                >
                                    {loadingMore && <Spinner className="h-4 w-4" />}
                                    {t('adminBillingLoadMore')}
                                </button>
                            )}
                        </div>
                    </>
                )}
            </main>
        </div>
    );
}
