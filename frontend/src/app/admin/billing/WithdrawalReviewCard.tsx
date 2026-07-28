'use client';

import { useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { Spinner } from '@/components/Spinner';
import { useI18n } from '@/context/I18nContext';
import {
    ApiError,
    api,
    type BillingAdminPendingWithdrawal,
    type BillingWithdrawalResolutionDecision,
    type BillingWithdrawalResolutionResponse,
} from '@/lib/api';
import { ATHENS_TIME_ZONE } from '@/lib/billingAdmin';

type WithdrawalReviewFormValues = {
    decision: '' | BillingWithdrawalResolutionDecision;
    adjustmentId: string;
    customerExplanation: string;
    finalManualReviewConfirmed: boolean;
};

type WithdrawalReviewCardProps = {
    review: BillingAdminPendingWithdrawal;
    onResolved: (
        resolution: BillingWithdrawalResolutionResponse,
    ) => void;
};

function formatDateTime(epochSeconds: number, locale: string): string {
    return new Intl.DateTimeFormat(locale, {
        timeZone: ATHENS_TIME_ZONE,
        dateStyle: 'medium',
        timeStyle: 'medium',
    }).format(new Date(epochSeconds * 1000));
}

export function WithdrawalReviewCard({
    review,
    onResolved,
}: WithdrawalReviewCardProps) {
    const { locale, t } = useI18n();
    const [resolveError, setResolveError] = useState('');
    const {
        formState: { errors, isSubmitting },
        control,
        handleSubmit,
        register,
    } = useForm<WithdrawalReviewFormValues>({
        defaultValues: {
            decision: '',
            adjustmentId: '',
            customerExplanation: '',
            finalManualReviewConfirmed: false,
        },
    });
    const decision = useWatch({
        control,
        name: 'decision',
    });
    const hasCompletedManualActions = (
        review.available_adjustments.length > 0
    );

    const submitResolution = handleSubmit(async (values) => {
        if (!values.decision) {
            return;
        }
        setResolveError('');
        try {
            const resolution = await api.resolveBillingWithdrawal(
                review.withdrawal_id,
                {
                    decision: values.decision,
                    adjustment_id: values.decision
                        === 'accepted_refunded'
                        ? values.adjustmentId
                        : null,
                    customer_explanation: (
                        values.customerExplanation
                    ),
                    final_manual_review_confirmed: true,
                },
            );
            onResolved(resolution);
        } catch (error) {
            // Final review records are never retried automatically.
            setResolveError(
                error instanceof ApiError && error.status === 403
                    ? t('adminBillingRecentSignInRequired')
                    : t('adminBillingWithdrawalResolveError'),
            );
        }
    });

    return (
        <article
            className="overflow-hidden rounded-3xl border border-amber-200 bg-white shadow-sm"
            data-testid={`billing-admin-withdrawal-${review.withdrawal_id}`}
        >
            <div className="border-b border-amber-200 bg-amber-50 p-5 sm:p-7">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <span className="rounded-full bg-amber-700 px-3 py-1 text-xs font-bold text-white">
                            {t('adminBillingWithdrawalPendingBadge')}
                        </span>
                        <h3 className="mt-4 text-2xl font-extrabold">
                            {t('adminBillingWithdrawalReviewTitle')}
                        </h3>
                        <p className="mt-2 break-all font-mono text-xs">
                            {review.withdrawal_id}
                        </p>
                    </div>
                    <p className="text-sm font-semibold text-amber-950">
                        {formatDateTime(review.submitted_at, locale)}
                        {' · '}
                        {ATHENS_TIME_ZONE}
                    </p>
                </div>
            </div>

            <div className="grid gap-5 p-5 sm:grid-cols-2 sm:p-7">
                <div>
                    <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--muted)]">
                        {t('adminBillingPurchaseId')}
                    </p>
                    <p className="mt-1 break-all font-mono text-xs">
                        {review.purchase_id}
                    </p>
                </div>
                <div>
                    <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--muted)]">
                        {t('adminBillingContractConcludedAt')}
                    </p>
                    <p className="mt-1 text-sm">
                        {formatDateTime(
                            review.contract_concluded_at,
                            locale,
                        )}
                    </p>
                </div>
                <div>
                    <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--muted)]">
                        {t('adminBillingCustomerName')}
                    </p>
                    <p className="mt-1 text-sm">{review.confirmed_name}</p>
                </div>
                <div>
                    <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--muted)]">
                        {t('adminBillingCustomerEmail')}
                    </p>
                    <p className="mt-1 break-all text-sm">
                        {review.confirmation_email}
                    </p>
                </div>
            </div>

            <form
                className="space-y-6 border-t border-[var(--border)] p-5 sm:p-7"
                onSubmit={(event) => void submitResolution(event)}
                noValidate
            >
                <fieldset className="space-y-3">
                    <legend className="text-lg font-extrabold">
                        {t('adminBillingWithdrawalDecision')}
                    </legend>
                    <label className="flex items-start gap-3 rounded-2xl border border-emerald-300 bg-emerald-50 p-4 text-sm leading-6">
                        <input
                            type="radio"
                            value="accepted_refunded"
                            disabled={!hasCompletedManualActions}
                            className="mt-1 h-5 w-5 shrink-0"
                            {...register('decision', {
                                required: (
                                    t(
                                        'adminBillingWithdrawalDecisionRequired',
                                    )
                                ),
                            })}
                        />
                        <span>
                            <strong className="block">
                                {t('adminBillingWithdrawalAccept')}
                            </strong>
                            {t('adminBillingWithdrawalAcceptHelp')}
                        </span>
                    </label>
                    {!hasCompletedManualActions && (
                        <p
                            role="status"
                            className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm font-semibold leading-6 text-amber-950"
                        >
                            {t(
                                'adminBillingWithdrawalNeedsRefundEvidence',
                            )}
                        </p>
                    )}
                    <label className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6">
                        <input
                            type="radio"
                            value="rejected"
                            className="mt-1 h-5 w-5 shrink-0"
                            {...register('decision', {
                                required: (
                                    t(
                                        'adminBillingWithdrawalDecisionRequired',
                                    )
                                ),
                            })}
                        />
                        <span>
                            <strong className="block">
                                {t('adminBillingWithdrawalReject')}
                            </strong>
                            {t('adminBillingWithdrawalRejectHelp')}
                        </span>
                    </label>
                    {errors.decision && (
                        <p role="alert" className="text-sm text-red-700">
                            {errors.decision.message}
                        </p>
                    )}
                </fieldset>

                {decision === 'accepted_refunded' && (
                    <label className="grid gap-2 text-sm font-semibold">
                        {t('adminBillingWithdrawalAdjustmentEvidence')}
                        <select
                            className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3"
                            {...register('adjustmentId', {
                                required: (
                                    t(
                                        'adminBillingWithdrawalAdjustmentRequired',
                                    )
                                ),
                            })}
                        >
                            <option value="">
                                {t('adminBillingWithdrawalSelectAdjustment')}
                            </option>
                            {review.available_adjustments.map(
                                (adjustment) => (
                                    <option
                                        key={adjustment.adjustment_id}
                                        value={adjustment.adjustment_id}
                                    >
                                        {adjustment.stripe_refund_id}
                                        {' · MARK '}
                                        {adjustment.aade_mark}
                                        {' · '}
                                        {(
                                            adjustment.amount_cents / 100
                                        ).toFixed(2)}
                                        {' '}
                                        {adjustment.currency.toUpperCase()}
                                    </option>
                                ),
                            )}
                        </select>
                        {errors.adjustmentId && (
                            <span role="alert" className="text-xs text-red-700">
                                {errors.adjustmentId.message}
                            </span>
                        )}
                    </label>
                )}

                <label className="grid gap-2 text-sm font-semibold">
                    {t('adminBillingWithdrawalCustomerExplanation')}
                    <textarea
                        aria-label={t(
                            'adminBillingWithdrawalCustomerExplanation',
                        )}
                        rows={5}
                        maxLength={1000}
                        className="rounded-xl border border-[var(--border-strong)] p-3 leading-6"
                        {...register('customerExplanation', {
                            required: (
                                t(
                                    'adminBillingWithdrawalExplanationInvalid',
                                )
                            ),
                            minLength: {
                                value: 20,
                                message: (
                                    t(
                                        'adminBillingWithdrawalExplanationInvalid',
                                    )
                                ),
                            },
                            maxLength: {
                                value: 1000,
                                message: (
                                    t(
                                        'adminBillingWithdrawalExplanationInvalid',
                                    )
                                ),
                            },
                            validate: (value) => (
                                value.trim() === value
                                || t(
                                    'adminBillingWithdrawalExplanationInvalid',
                                )
                            ),
                        })}
                    />
                    <span className="text-xs font-normal leading-5 text-[var(--muted)]">
                        {t('adminBillingWithdrawalExplanationHelp')}
                    </span>
                    {errors.customerExplanation && (
                        <span role="alert" className="text-xs text-red-700">
                            {errors.customerExplanation.message}
                        </span>
                    )}
                </label>

                <label className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[#fafaf8] p-4 text-sm font-semibold leading-6">
                    <input
                        type="checkbox"
                        className="mt-1 h-5 w-5 shrink-0"
                        {...register('finalManualReviewConfirmed', {
                            required: (
                                t(
                                    'adminBillingFinalWithdrawalReviewConfirm',
                                )
                            ),
                        })}
                    />
                    <span>
                        {t(
                            'adminBillingFinalWithdrawalReviewConfirm',
                        )}
                    </span>
                </label>
                {errors.finalManualReviewConfirmed && (
                    <p role="alert" className="text-sm text-red-700">
                        {errors.finalManualReviewConfirmed.message}
                    </p>
                )}

                {resolveError && (
                    <p
                        role="alert"
                        className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900"
                    >
                        {resolveError}
                    </p>
                )}

                <button
                    type="submit"
                    disabled={isSubmitting}
                    className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[var(--foreground)] px-5 font-bold text-white disabled:opacity-60"
                >
                    {isSubmitting && <Spinner className="h-4 w-4" />}
                    {isSubmitting
                        ? t('adminBillingRecording')
                        : t('adminBillingResolveWithdrawal')}
                </button>
            </form>
        </article>
    );
}
