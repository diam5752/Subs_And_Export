'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CoinsIcon } from '@/components/icons';
import { Spinner } from '@/components/Spinner';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';
import { formatPoints } from '@/lib/points';

export type ProcessingGateStage = 'auth' | 'cost';

interface ProcessingGateModalProps {
    isOpen: boolean;
    stage: ProcessingGateStage;
    cost: number;
    balance: number | null;
    isBalanceLoading: boolean;
    error: string;
    onClose: () => void;
    onAuthenticated: () => Promise<void>;
    onConfirm: () => Promise<void>;
}

export function ProcessingGateModal({
    isOpen,
    stage,
    cost,
    balance,
    isBalanceLoading,
    error,
    onClose,
    onAuthenticated,
    onConfirm,
}: ProcessingGateModalProps) {
    const { login, register } = useAuth();
    const { t } = useI18n();
    const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [authError, setAuthError] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const emailRef = useRef<HTMLInputElement>(null);

    const close = useCallback(() => {
        onClose();
    }, [onClose]);

    useEffect(() => {
        if (!isOpen) return;

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') close();
        };

        document.addEventListener('keydown', handleKeyDown);
        document.body.style.overflow = 'hidden';
        if (stage === 'auth') {
            setAuthMode('login');
            setAuthError('');
            window.setTimeout(() => emailRef.current?.focus(), 50);
        }

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
        };
    }, [close, isOpen, stage]);

    const handleAuthSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setAuthError('');
        setIsSubmitting(true);

        try {
            if (authMode === 'register') {
                await register(email, password, name);
            } else {
                await login(email, password);
            }
            await onAuthenticated();
        } catch (authFailure) {
            setAuthError(authFailure instanceof Error ? authFailure.message : t('processingGateAuthError'));
        } finally {
            setIsSubmitting(false);
        }
    };

    if (!isOpen) return null;

    const canAfford = balance !== null && balance >= cost;
    const missingPoints = balance === null ? 0 : Math.max(0, cost - balance);
    const title = stage === 'auth' ? t('processingGateAuthTitle') : t('processingGateCostTitle');

    return (
        <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="processing-gate-title"
            aria-describedby="processing-gate-description"
            className="fixed inset-0 z-[70] flex items-end justify-center bg-black/55 px-4 pt-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] backdrop-blur-sm sm:items-center sm:py-8"
            onClick={close}
            data-testid="processing-gate"
        >
            <div
                className="relative w-full max-w-md overflow-hidden rounded-[24px] border border-black/10 bg-white shadow-2xl"
                onClick={(event) => event.stopPropagation()}
            >
                <div className="h-1 bg-[var(--accent)]" />
                <div className="p-6 sm:p-8">
                    <div className="mb-6 flex items-start justify-between gap-4">
                        <div>
                            <span className="mb-2 block text-[11px] font-bold uppercase tracking-[0.18em] text-[var(--accent)]">
                                {stage === 'auth' ? t('processingGateAuthKicker') : t('processingGateCostKicker')}
                            </span>
                            <h2 id="processing-gate-title" className="text-2xl font-bold tracking-[-0.04em] text-[var(--foreground)]">
                                {title}
                            </h2>
                            <p id="processing-gate-description" className="mt-2 text-sm leading-6 text-[var(--muted)]">
                                {stage === 'auth' ? t('processingGateAuthDescription') : t('processingGateCostDescription')}
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={close}
                            className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-[var(--border)] text-[var(--muted)] transition-colors hover:bg-[#f5f5f4] hover:text-[var(--foreground)]"
                            aria-label={t('closeLabel')}
                        >
                            <span aria-hidden="true">✕</span>
                        </button>
                    </div>

                    {stage === 'auth' ? (
                        <form onSubmit={handleAuthSubmit} className="space-y-4">
                            {authMode === 'register' && (
                                <div>
                                    <label htmlFor="gate-name" className="auth-label">{t('registerNameLabel')}</label>
                                    <input
                                        id="gate-name"
                                        type="text"
                                        value={name}
                                        onChange={(event) => setName(event.target.value)}
                                        className="input-field"
                                        autoComplete="name"
                                        required
                                    />
                                </div>
                            )}
                            <div>
                                <label htmlFor="gate-email" className="auth-label">{t('loginEmailLabel')}</label>
                                <input
                                    ref={emailRef}
                                    id="gate-email"
                                    type="email"
                                    value={email}
                                    onChange={(event) => setEmail(event.target.value)}
                                    className="input-field"
                                    autoComplete="email"
                                    required
                                />
                            </div>
                            <div>
                                <label htmlFor="gate-password" className="auth-label">{t('loginPasswordLabel')}</label>
                                <input
                                    id="gate-password"
                                    type="password"
                                    value={password}
                                    onChange={(event) => setPassword(event.target.value)}
                                    className="input-field"
                                    autoComplete={authMode === 'register' ? 'new-password' : 'current-password'}
                                    minLength={authMode === 'register' ? 12 : undefined}
                                    required
                                />
                            </div>

                            {(authError || error) && (
                                <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                                    {authError || error}
                                </p>
                            )}

                            <button
                                type="submit"
                                disabled={isSubmitting}
                                aria-busy={isSubmitting}
                                className="btn-primary flex min-h-12 w-full items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {isSubmitting && <Spinner className="h-4 w-4" />}
                                {authMode === 'register' ? t('processingGateRegisterSubmit') : t('processingGateLoginSubmit')}
                            </button>

                            <button
                                type="button"
                                onClick={() => {
                                    setAuthMode((mode) => mode === 'login' ? 'register' : 'login');
                                    setAuthError('');
                                }}
                                className="min-h-11 w-full text-sm font-semibold text-[var(--foreground)] hover:text-[var(--accent)]"
                            >
                                {authMode === 'login' ? t('processingGateCreateAccount') : t('processingGateUseLogin')}
                            </button>
                        </form>
                    ) : (
                        <div className="space-y-5">
                            <div className="rounded-2xl border border-[#e7dfbd] bg-[#fffdf3] p-5">
                                <div className="flex items-center justify-between gap-4">
                                    <span className="text-sm font-medium text-[var(--muted)]">{t('processingGateCostLabel')}</span>
                                    <span className="flex items-center gap-2 text-2xl font-bold text-[var(--foreground)]">
                                        <CoinsIcon className="h-6 w-6 text-[#c99a00]" />
                                        {formatPoints(cost)}
                                    </span>
                                </div>
                                <div className="my-4 h-px bg-[#ece4c8]" />
                                <div className="flex items-center justify-between gap-4 text-sm">
                                    <span className="text-[var(--muted)]">{t('processingGateBalanceLabel')}</span>
                                    <strong className="text-[var(--foreground)]">
                                        {isBalanceLoading || balance === null ? '—' : formatPoints(balance)}
                                    </strong>
                                </div>
                            </div>

                            {error && (
                                <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                                    {error}
                                </p>
                            )}
                            {!isBalanceLoading && balance !== null && !canAfford && (
                                <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                                    {t('processingGateInsufficient', { count: missingPoints })}
                                </p>
                            )}

                            <p className="text-xs leading-5 text-[var(--muted)]">{t('processingGateChargeNote')}</p>

                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                <button
                                    type="button"
                                    onClick={close}
                                    className="min-h-12 rounded-xl border border-[var(--border)] bg-white px-4 font-semibold text-[var(--foreground)] hover:bg-[#f5f5f4]"
                                >
                                    {t('processingGateCancel')}
                                </button>
                                <button
                                    type="button"
                                    onClick={() => void onConfirm()}
                                    disabled={isBalanceLoading || !canAfford}
                                    className="btn-primary min-h-12 px-4 disabled:cursor-not-allowed disabled:opacity-45"
                                >
                                    {t('processingGateConfirm', { cost })}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
