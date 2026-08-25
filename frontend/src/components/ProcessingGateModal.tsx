'use client';

import React, {
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { CoinsIcon } from '@/components/icons';
import { Spinner } from '@/components/Spinner';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';
import { formatPoints } from '@/lib/points';

// Email login remains immediately interactive. The Google SDK controller is
// requested only when this auth-only modal is actually rendered.
const GoogleSignInControl = dynamic(() => (
    import('@/components/GoogleSignInControl').then((module) => module.GoogleSignInControl)
));

export type ProcessingGateStage = 'auth' | 'cost';

interface ProcessingGateModalProps {
    isOpen: boolean;
    stage: ProcessingGateStage;
    initialScrollPosition?: { x: number; y: number };
    cost: number;
    balance: number | null;
    requiresPaidCredits?: boolean;
    isBalanceLoading: boolean;
    error: string;
    onClose: () => void;
    onAuthenticated: () => Promise<void>;
    onConfirm: () => Promise<void>;
    onPurchaseCredits?: () => void;
}

export function ProcessingGateModal({
    isOpen,
    stage,
    initialScrollPosition,
    cost,
    balance,
    requiresPaidCredits = true,
    isBalanceLoading,
    error,
    onClose,
    onAuthenticated,
    onConfirm,
    onPurchaseCredits,
}: ProcessingGateModalProps) {
    const { login, register } = useAuth();
    const { t } = useI18n();
    const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [authError, setAuthError] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [isCostActionPending, setIsCostActionPending] = useState(false);
    const dialogRef = useRef<HTMLDivElement>(null);
    const closeButtonRef = useRef<HTMLButtonElement>(null);
    const emailRef = useRef<HTMLInputElement>(null);
    const costActionRef = useRef<HTMLButtonElement>(null);
    const returnFocusRef = useRef<HTMLElement | null>(null);
    const authSessionGenerationRef = useRef(0);
    const costActionInFlightRef = useRef(false);

    const close = useCallback(() => {
        onClose();
    }, [onClose]);

    const confirmCostAction = useCallback(async () => {
        if (costActionInFlightRef.current || isBalanceLoading) return;
        costActionInFlightRef.current = true;
        setIsCostActionPending(true);
        try {
            await onConfirm();
        } finally {
            costActionInFlightRef.current = false;
            setIsCostActionPending(false);
        }
    }, [isBalanceLoading, onConfirm]);

    const purchaseCredits = useCallback(() => {
        if (
            costActionInFlightRef.current
            || isBalanceLoading
            || !onPurchaseCredits
        ) return;
        costActionInFlightRef.current = true;
        setIsCostActionPending(true);
        onPurchaseCredits();
    }, [isBalanceLoading, onPurchaseCredits]);

    useEffect(() => {
        if (!isOpen) return;

        const sessionGeneration = authSessionGenerationRef.current + 1;
        authSessionGenerationRef.current = sessionGeneration;
        return () => {
            if (authSessionGenerationRef.current === sessionGeneration) {
                authSessionGenerationRef.current += 1;
            }
        };
    }, [isOpen]);

    useLayoutEffect(() => {
        if (!isOpen) return;

        // Lock before WebKit paints the newly mounted dialog. A passive effect
        // leaves a frame where iOS may auto-adjust the document by a few pixels,
        // making the background jump and restoring to the wrong position.
        const root = document.documentElement;
        const body = document.body;
        const scrollX = initialScrollPosition?.x ?? window.scrollX;
        const scrollY = initialScrollPosition?.y ?? window.scrollY;
        const previousRootStyles = {
            overflow: root.style.overflow,
            overscrollBehavior: root.style.overscrollBehavior,
            scrollBehavior: root.style.scrollBehavior,
            height: root.style.height,
        };
        const previousBodyStyles = {
            overflow: body.style.overflow,
            overscrollBehavior: body.style.overscrollBehavior,
            position: body.style.position,
            top: body.style.top,
            left: body.style.left,
            width: body.style.width,
            height: body.style.height,
        };
        const restoreLockedPosition = () => {
            if (window.scrollX !== scrollX || window.scrollY !== scrollY) {
                window.scrollTo(scrollX, scrollY);
            }
        };

        root.style.overflow = 'hidden';
        root.style.overscrollBehavior = 'none';
        root.style.height = '100%';
        body.style.overflow = 'hidden';
        body.style.overscrollBehavior = 'none';
        body.style.position = 'fixed';
        body.style.top = `${-scrollY}px`;
        body.style.left = `${-scrollX}px`;
        body.style.width = '100%';
        body.style.height = '100%';
        window.addEventListener('scroll', restoreLockedPosition, { passive: true });

        return () => {
            window.removeEventListener('scroll', restoreLockedPosition);
            root.style.overflow = previousRootStyles.overflow;
            root.style.overscrollBehavior = previousRootStyles.overscrollBehavior;
            root.style.height = previousRootStyles.height;
            body.style.overflow = previousBodyStyles.overflow;
            body.style.overscrollBehavior = previousBodyStyles.overscrollBehavior;
            body.style.position = previousBodyStyles.position;
            body.style.top = previousBodyStyles.top;
            body.style.left = previousBodyStyles.left;
            body.style.width = previousBodyStyles.width;
            body.style.height = previousBodyStyles.height;

            // Global CSS uses smooth scrolling. Override it for this one
            // restoration so closing the modal cannot visibly animate the page.
            root.style.scrollBehavior = 'auto';
            window.scrollTo(scrollX, scrollY);
            root.style.scrollBehavior = previousRootStyles.scrollBehavior;
        };
    }, [initialScrollPosition?.x, initialScrollPosition?.y, isOpen]);

    useEffect(() => {
        if (!isOpen) return;

        returnFocusRef.current = document.activeElement instanceof HTMLElement
            ? document.activeElement
            : null;

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                close();
                return;
            }
            if (event.key !== 'Tab' || !dialogRef.current) return;

            const focusable = Array.from(
                dialogRef.current.querySelectorAll<HTMLElement>(
                    'a[href], button:not([disabled]), input:not([disabled]), '
                    + 'select:not([disabled]), textarea:not([disabled]), '
                    + '[tabindex]:not([tabindex="-1"])',
                ),
            ).filter((element) => (
                element.getAttribute('aria-hidden') !== 'true'
                && element.getClientRects().length > 0
            ));

            if (focusable.length === 0) {
                event.preventDefault();
                dialogRef.current.focus({ preventScroll: true });
                return;
            }

            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            const activeElement = document.activeElement;
            if (
                event.shiftKey
                && (activeElement === first || !dialogRef.current.contains(activeElement))
            ) {
                event.preventDefault();
                last.focus({ preventScroll: true });
            } else if (
                !event.shiftKey
                && (activeElement === last || !dialogRef.current.contains(activeElement))
            ) {
                event.preventDefault();
                first.focus({ preventScroll: true });
            }
        };

        document.addEventListener('keydown', handleKeyDown);

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            const returnTarget = returnFocusRef.current;
            returnFocusRef.current = null;
            queueMicrotask(() => {
                if (returnTarget?.isConnected) {
                    returnTarget.focus({ preventScroll: true });
                }
            });
        };
    }, [close, isOpen]);

    useEffect(() => {
        if (!isOpen) return;

        if (stage === 'auth') {
            emailRef.current?.focus({ preventScroll: true });
            return;
        }

        const costAction = costActionRef.current;
        if (costAction && !costAction.disabled) {
            costAction.focus({ preventScroll: true });
        } else {
            closeButtonRef.current?.focus({ preventScroll: true });
        }
    }, [isOpen, stage]);

    const handleAuthSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const sessionGeneration = authSessionGenerationRef.current;
        setAuthError('');
        setIsSubmitting(true);

        try {
            if (authMode === 'register') {
                await register(email, password, name);
            } else {
                await login(email, password);
            }
            if (sessionGeneration !== authSessionGenerationRef.current) {
                return;
            }
            await onAuthenticated();
        } catch (authFailure) {
            if (sessionGeneration === authSessionGenerationRef.current) {
                setAuthError(authFailure instanceof Error
                    ? authFailure.message
                    : t('processingGateAuthError'));
            }
        } finally {
            if (sessionGeneration === authSessionGenerationRef.current) {
                setIsSubmitting(false);
            }
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
            className="fixed inset-0 z-[70] flex items-end justify-center overflow-y-auto overscroll-contain bg-black/55 px-4 pt-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] backdrop-blur-sm sm:items-center sm:py-8"
            onClick={close}
            data-testid="processing-gate"
        >
            <div
                ref={dialogRef}
                tabIndex={-1}
                className="relative max-h-full w-full max-w-md overflow-x-hidden overflow-y-auto overscroll-contain rounded-[24px] border border-black/10 bg-white shadow-2xl"
                onClick={(event) => event.stopPropagation()}
                data-testid="processing-gate-card"
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
                            ref={closeButtonRef}
                            type="button"
                            onClick={close}
                            className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-[var(--border)] text-[var(--muted)] transition-colors hover:bg-[#f5f5f4] hover:text-[var(--foreground)]"
                            aria-label={t('closeLabel')}
                        >
                            <span aria-hidden="true">✕</span>
                        </button>
                    </div>

                    {stage === 'auth' ? (
                        <div className="space-y-4">
                            <GoogleSignInControl
                                onAuthenticated={onAuthenticated}
                                recoveryStrategy="reinitialize"
                            />
                            <div className="auth-divider !my-0">
                                <span>{t('loginOrEmail')}</span>
                            </div>
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

                            {authMode === 'register' && (
                                <p
                                    id="processing-gate-register-legal-notice"
                                    className="text-xs leading-5 text-[var(--muted)]"
                                >
                                    {t('registerLegalIntro')}{' '}
                                    <Link
                                        href="/terms"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="rounded-sm font-semibold text-[var(--accent)] underline underline-offset-2 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2"
                                    >
                                        {t('registerLegalTermsLink')}
                                    </Link>{' '}
                                    {t('registerLegalConnector')}{' '}
                                    <Link
                                        href="/privacy"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="rounded-sm font-semibold text-[var(--accent)] underline underline-offset-2 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2"
                                    >
                                        {t('registerLegalPrivacyLink')}
                                    </Link>.
                                </p>
                            )}

                            <button
                                type="submit"
                                disabled={isSubmitting}
                                aria-busy={isSubmitting}
                                aria-describedby={authMode === 'register'
                                    ? 'processing-gate-register-legal-notice'
                                    : undefined}
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
                        </div>
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
                                    <span className="text-[var(--muted)]">
                                        {t(requiresPaidCredits
                                            ? 'processingGateBalanceLabel'
                                            : 'processingGateTotalBalanceLabel')}
                                    </span>
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

                            <p className="text-xs leading-5 text-[var(--muted)]">
                                {t(requiresPaidCredits
                                    ? 'processingGateChargeNote'
                                    : 'processingGateLocalChargeNote')}
                            </p>

                            <div className={`grid grid-cols-1 gap-3 ${
                                canAfford || onPurchaseCredits ? 'sm:grid-cols-2' : ''
                            }`}>
                                <button
                                    type="button"
                                    onClick={close}
                                    className="min-h-12 rounded-xl border border-[var(--border)] bg-white px-4 font-semibold text-[var(--foreground)] hover:bg-[#f5f5f4]"
                                >
                                    {t('processingGateCancel')}
                                </button>
                                {canAfford ? (
                                    <button
                                        ref={costActionRef}
                                        type="button"
                                        onClick={() => void confirmCostAction()}
                                        disabled={isBalanceLoading || isCostActionPending}
                                        aria-busy={isCostActionPending}
                                        className="btn-primary flex min-h-12 items-center justify-center gap-2 px-4 disabled:cursor-not-allowed disabled:opacity-45"
                                    >
                                        {isCostActionPending && <Spinner className="h-4 w-4" />}
                                        {t('processingGateConfirm', { cost })}
                                    </button>
                                ) : onPurchaseCredits ? (
                                    <button
                                        ref={costActionRef}
                                        type="button"
                                        onClick={purchaseCredits}
                                        disabled={isBalanceLoading || isCostActionPending}
                                        aria-busy={isCostActionPending}
                                        className="btn-primary flex min-h-12 items-center justify-center gap-2 px-4 disabled:cursor-not-allowed disabled:opacity-45"
                                    >
                                        {isCostActionPending && <Spinner className="h-4 w-4" />}
                                        {t('processingGateBuyCredits')}
                                    </button>
                                ) : null}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
