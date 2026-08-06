'use client';

import { useCallback, useEffect, useState, useMemo, useRef } from 'react';
import { useAuth } from '@/context/AuthContext';
import { usePoints } from '@/context/PointsContext';
import { api, JobResponse } from '@/lib/api';
import { formatDate, buildStaticUrl } from '@/lib/utils';
import { useI18n } from '@/context/I18nContext';
import { LanguageToggle } from '@/components/LanguageToggle';
import { ProcessView, ProcessingOptions } from '@/features/process/ProcessView';
import { AccountView } from '@/components/AccountView';
import { CreditsBadge } from '@/components/CreditsBadge';
import { CreditPurchaseDialog } from '@/components/CreditPurchaseDialog';
import { ProcessingGateModal, type ProcessingGateStage } from '@/components/ProcessingGateModal';
import { useJobs } from '@/hooks/useJobs';
import { useJobPolling, JobPollingCallbacks } from '@/hooks/useJobPolling';
import {
  processVideoCostForSelection,
  transcribeProviderRequiresPaidCredits,
} from '@/lib/points';
import { paidCreditLegalPublicationIsApproved } from '@/lib/paidCreditLegal';
import Link from 'next/link';
import { BrandLogo } from '@/components/BrandLogo';
import { ProfileAvatar } from '@/components/ProfileAvatar';

const statusStyles: Record<string, string> = {
  completed: 'bg-green-500/15 text-green-300 border-green-500/30',
  processing: 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/40',
  pending: 'bg-[var(--muted)]/10 text-[var(--muted)] border-[var(--border)]',
  failed: 'bg-[var(--danger)]/15 text-[var(--danger)] border-[var(--danger)]/40',
};

const RESTORABLE_ACTIVE_JOB_STATUSES = new Set(['pending', 'processing', 'cancelling']);
const CANCELLABLE_JOB_STATUSES = new Set(['pending', 'processing']);

type PendingProcessingAction =
  | { kind: 'new'; options: ProcessingOptions }
  | { kind: 'reprocess'; sourceJobId: string; options: ProcessingOptions };

export default function DashboardPage() {
  const { user, isLoading, logout, refreshUser } = useAuth();
  const paidCreditSalesUiApproved = paidCreditLegalPublicationIsApproved();
  const {
    balance,
    aiSpendableBalance,
    setBalance: setPointsBalance,
    setWallet,
    refreshBalance,
  } = usePoints();
  const { t } = useI18n();
  const didRestoreSession = useRef(false);
  const activeUploadAbortRef = useRef<AbortController | null>(null);

  // Custom Hooks
  const {
    selectedJob,
    setSelectedJob,
    recentJobs,
    jobsLoading,
    loadJobs,
    currentPage,
    totalPages,
    nextPage,
    prevPage,
    totalJobs,
    pageSize,
  } = useJobs();


  // Local Processing State
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [processError, setProcessError] = useState('');
  const [canCancelProcessing, setCanCancelProcessing] = useState(false);
  const [pendingProcessingAction, setPendingProcessingAction] = useState<PendingProcessingAction | null>(null);
  const [processingGateStage, setProcessingGateStage] = useState<ProcessingGateStage | null>(null);
  const [processingGateError, setProcessingGateError] = useState('');
  const [isGateBalanceLoading, setIsGateBalanceLoading] = useState(false);
  const [showCreditPurchase, setShowCreditPurchase] = useState(false);
  const [checkoutNotice, setCheckoutNotice] = useState('');
  const [checkoutContractAvailable, setCheckoutContractAvailable] = useState(false);

  // Account Modal State
  const [showAccountPanel, setShowAccountPanel] = useState(false);
  const [activeAccountTab, setActiveAccountTab] = useState<'profile' | 'history'>('profile');
  const [accountMessage, setAccountMessage] = useState('');
  const [accountError, setAccountError] = useState('');
  const [accountSaving, setAccountSaving] = useState(false);
  const accountDialogRef = useRef<HTMLDivElement>(null);
  const accountCloseButtonRef = useRef<HTMLButtonElement>(null);
  const accountReturnFocusRef = useRef<HTMLElement | null>(null);

  const handleCloseAccountPanel = useCallback(() => {
    setShowAccountPanel(false);
  }, [setShowAccountPanel]);

  useEffect(() => {
    if (!showAccountPanel) return;

    const handleAccountDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        handleCloseAccountPanel();
        return;
      }
      if (event.key !== 'Tab' || !accountDialogRef.current) return;

      const focusable = Array.from(
        accountDialogRef.current.querySelectorAll<HTMLElement>(
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
        accountDialogRef.current.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;
      if (event.shiftKey && (activeElement === first || !accountDialogRef.current.contains(activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (activeElement === last || !accountDialogRef.current.contains(activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleAccountDialogKeyDown);
    queueMicrotask(() => accountCloseButtonRef.current?.focus());

    return () => {
      document.removeEventListener('keydown', handleAccountDialogKeyDown);
      const returnTarget = accountReturnFocusRef.current;
      queueMicrotask(() => {
        if (returnTarget?.isConnected) returnTarget.focus();
      });
    };
  }, [handleCloseAccountPanel, showAccountPanel]);

  const handleLogout = useCallback(async () => {
    setAccountError('');
    try {
      await logout();
      setShowAccountPanel(false);
    } catch {
      setAccountError(t('signOutError'));
    }
  }, [logout, t]);

  // Restore session
  useEffect(() => {
    if (!user || selectedFile || didRestoreSession.current) return;
    didRestoreSession.current = true;

    const restoreSession = async () => {
      const lastJobId = localStorage.getItem('lastActiveJobId');
      if (lastJobId && !selectedJob && !jobId) {
        try {
          const job = await api.getJobStatus(lastJobId);
          const completedFilesAreAvailable = job.status !== 'completed'
            || Boolean(job.result_data && !job.result_data.files_missing);

          if (RESTORABLE_ACTIVE_JOB_STATUSES.has(job.status)) {
            setJobId(job.id);
            setIsProcessing(true);
            setCanCancelProcessing(CANCELLABLE_JOB_STATUSES.has(job.status));
            setProgress(job.progress ?? 0);
            setStatusMessage(
              job.status === 'cancelling'
                ? t('cancellationRequested')
                : job.message || t('statusProcessingEllipsis'),
            );
            setProcessError('');
            return;
          }

          // A completed job whose local artifacts were cleaned up cannot render
          // a preview or transcript, so it must not reopen as a broken editor.
          if (job.status === 'completed' && completedFilesAreAvailable) {
            setSelectedJob(job);
          } else {
            localStorage.removeItem('lastActiveJobId');
          }
        } catch (err) {
          console.warn('Failed to restore session job:', err);
          localStorage.removeItem('lastActiveJobId');
        }
      }
    };
    void restoreSession();
  }, [jobId, selectedFile, selectedJob, setSelectedJob, t, user]);

  // Persist both in-flight and completed sessions so a reload can resume
  // polling or reopen the finished editor respectively.
  useEffect(() => {
    const restorableJobId = jobId ?? selectedJob?.id;
    if (restorableJobId) {
      localStorage.setItem('lastActiveJobId', restorableJobId);
    }
  }, [jobId, selectedJob]);

  const refreshActivity = useCallback(async () => {
    await loadJobs();
  }, [loadJobs]);

  // Polling callbacks
  const pollingCallbacks = useMemo<JobPollingCallbacks>(() => ({
    onProgress: (progress: number, message: string) => {
      setProgress(progress);
      setStatusMessage(message);
    },
    onComplete: (job: JobResponse) => {
      setIsProcessing(false);
      setCanCancelProcessing(false);
      setJobId(null);
      setSelectedJob(job);
      setProcessError('');
      refreshActivity();
    },
    onFailed: (errorMessage: string) => {
      localStorage.removeItem('lastActiveJobId');
      setProcessError(errorMessage);
      setIsProcessing(false);
      setCanCancelProcessing(false);
      setJobId(null);
      refreshActivity();
    },
    onError: (errorMessage: string) => {
      setIsProcessing(false);
      setCanCancelProcessing(false);
      setProcessError(errorMessage);
    },
  }), [refreshActivity, setSelectedJob]);

  // Cancel processing handler
  const handleCancelProcessing = useCallback(async () => {
    const activeUpload = activeUploadAbortRef.current;
    if (activeUpload) {
      activeUploadAbortRef.current = null;
      activeUpload.abort();
      setCanCancelProcessing(false);
      setIsProcessing(false);
      setProcessError(t('processingCancelled'));
      return;
    }
    if (!jobId) return;
    try {
      await api.cancelJob(jobId);
      setCanCancelProcessing(false);
      setStatusMessage(t('cancellationRequested'));
      setProcessError('');
      await refreshActivity();
    } catch (err) {
      // If cancel fails, just continue polling
      console.error('Cancel failed:', err);
    }
  }, [jobId, refreshActivity, t]);

  // Use the polling hook
  useJobPolling({
    jobId,
    callbacks: pollingCallbacks,
    t,
  });

  const executeStartProcessing = useCallback(async (options: ProcessingOptions) => {
    if (!selectedFile) return;

    const uploadController = new AbortController();
    activeUploadAbortRef.current = uploadController;
    setIsProcessing(true);
    setCanCancelProcessing(true);
    setProcessError('');
    setProgress(0);
    setSelectedJob(null);
    setStatusMessage(t('statusUploading'));

    const provider = options.transcribeProvider || 'mock';
    const selectedModel = options.transcribeMode || 'standard';
    const reportUploadProgress = (percent: number) => {
      setProgress(percent);
      setStatusMessage(`${t('statusUploading')} ${percent}%`);
    };
    const markUploadComplete = () => {
      if (activeUploadAbortRef.current === uploadController) {
        activeUploadAbortRef.current = null;
      }
      setCanCancelProcessing(false);
      setProgress(0);
      setStatusMessage(t('statusProcessing'));
    };

    try {
      const settings = {
        transcribe_tier: selectedModel,
        transcribe_provider: provider,
        source_duration_seconds: options.sourceDurationSeconds ?? null,
        video_quality: options.outputQuality,
        video_resolution: options.outputResolution,
        use_llm: options.useAI,
        context_prompt: options.contextPrompt,
        subtitle_position: options.subtitle_position,
        max_subtitle_lines: options.max_subtitle_lines,
        subtitle_color: options.subtitle_color,
        shadow_strength: options.shadow_strength,
        highlight_style: options.highlight_style,
        subtitle_size: options.subtitle_size,
        karaoke_enabled: options.karaoke_enabled,
        watermark_enabled: options.watermark_enabled,
      };

      const result = await api.processVideo(selectedFile, settings, {
        signal: uploadController.signal,
        onProgress: reportUploadProgress,
        onUploadComplete: markUploadComplete,
      });
      setJobId(result.id);
      setCanCancelProcessing(true);
      if (typeof result.balance === 'number') {
        setPointsBalance(result.balance);
      }
      void refreshBalance();
    } catch (err) {
      const uploadErrorCode = typeof err === 'object'
        && err !== null
        && 'code' in err
        && typeof err.code === 'string'
        ? err.code
        : null;
      if (uploadController.signal.aborted || uploadErrorCode === 'upload_cancelled') {
        setProcessError(t('processingCancelled'));
      } else if (uploadErrorCode === 'upload_network_error' || uploadErrorCode === 'upload_timeout') {
        setProcessError(t('uploadConnectionError'));
      } else if (uploadErrorCode === 'upload_http_error') {
        setProcessError(t('uploadFailed'));
      } else {
        setProcessError(err instanceof Error ? err.message : t('startProcessingError'));
      }
      setIsProcessing(false);
      setCanCancelProcessing(false);
    } finally {
      if (activeUploadAbortRef.current === uploadController) {
        activeUploadAbortRef.current = null;
      }
    }
  }, [refreshBalance, selectedFile, setPointsBalance, t, setSelectedJob]);

  const executeReprocessJob = useCallback(async (sourceJobId: string, options: ProcessingOptions) => {
    setIsProcessing(true);
    setCanCancelProcessing(false);
    setProcessError('');
    setProgress(0);
    setStatusMessage(t('statusProcessing'));

    const provider = options.transcribeProvider || 'mock';
    const selectedModel = options.transcribeMode || 'standard';

    try {
      const settings = {
        transcribe_tier: selectedModel,
        transcribe_provider: provider,
        video_quality: options.outputQuality,
        video_resolution: options.outputResolution,
        use_llm: options.useAI,
        context_prompt: options.contextPrompt,
        subtitle_position: options.subtitle_position,
        max_subtitle_lines: options.max_subtitle_lines,
        subtitle_color: options.subtitle_color,
        shadow_strength: options.shadow_strength,
        highlight_style: options.highlight_style,
        subtitle_size: options.subtitle_size,
        karaoke_enabled: options.karaoke_enabled,
        watermark_enabled: options.watermark_enabled,
      };

      const result = await api.reprocessJob(sourceJobId, settings);
      setJobId(result.id);
      setCanCancelProcessing(true);
      if (typeof result.balance === 'number') {
        setPointsBalance(result.balance);
      }
      void refreshBalance();
    } catch (err) {
      setProcessError(err instanceof Error ? err.message : t('startProcessingError'));
      setIsProcessing(false);
      setCanCancelProcessing(false);
    }
  }, [refreshBalance, setPointsBalance, t]);

  const pendingProcessingCost = useMemo(() => {
    if (!pendingProcessingAction) return 0;
    return processVideoCostForSelection(
      pendingProcessingAction.options.transcribeProvider,
      pendingProcessingAction.options.transcribeMode,
      pendingProcessingAction.options.sourceDurationSeconds,
    );
  }, [pendingProcessingAction]);

  const pendingProcessingRequiresPaidCredits = useMemo(
    () => transcribeProviderRequiresPaidCredits(
      pendingProcessingAction?.options.transcribeProvider,
    ),
    [pendingProcessingAction],
  );
  const processingGateBalance = pendingProcessingRequiresPaidCredits
    ? aiSpendableBalance
    : balance;

  const closeProcessingGate = useCallback(() => {
    setProcessingGateStage(null);
    setPendingProcessingAction(null);
    setProcessingGateError('');
    setIsGateBalanceLoading(false);
  }, []);

  const loadGateBalance = useCallback(async () => {
    setIsGateBalanceLoading(true);
    setProcessingGateError('');
    try {
      const points = await api.getPointsBalance();
      setWallet(points);
    } catch (err) {
      setProcessingGateError(err instanceof Error ? err.message : t('creditsError'));
    } finally {
      setIsGateBalanceLoading(false);
    }
  }, [setWallet, t]);

  const requestProcessingAction = useCallback((action: PendingProcessingAction) => {
    setPendingProcessingAction(action);
    setProcessingGateError('');

    if (!user) {
      setProcessingGateStage('auth');
      return;
    }

    setProcessingGateStage('cost');
    void loadGateBalance();
  }, [loadGateBalance, user]);

  const requestStartProcessing = useCallback(async (options: ProcessingOptions) => {
    requestProcessingAction({ kind: 'new', options });
  }, [requestProcessingAction]);

  const requestReprocessJob = useCallback(async (sourceJobId: string, options: ProcessingOptions) => {
    requestProcessingAction({ kind: 'reprocess', sourceJobId, options });
  }, [requestProcessingAction]);

  const handleGateAuthenticated = useCallback(async () => {
    if (!pendingProcessingAction) {
      closeProcessingGate();
      return;
    }

    setProcessingGateStage('cost');
    await loadGateBalance();
  }, [closeProcessingGate, loadGateBalance, pendingProcessingAction]);

  const handleGateConfirm = useCallback(async () => {
    if (
      !pendingProcessingAction
      || processingGateBalance === null
      || processingGateBalance < pendingProcessingCost
    ) return;

    const action = pendingProcessingAction;
    closeProcessingGate();
    if (action.kind === 'new') {
      await executeStartProcessing(action.options);
      return;
    }
    await executeReprocessJob(action.sourceJobId, action.options);
  }, [
    closeProcessingGate,
    executeReprocessJob,
    executeStartProcessing,
    pendingProcessingAction,
    pendingProcessingCost,
    processingGateBalance,
  ]);

  const closeCreditPurchase = useCallback(() => {
    setShowCreditPurchase(false);
    if (user) void refreshBalance();
  }, [refreshBalance, user]);

  useEffect(() => {
    if (!user || typeof window === 'undefined') return;
    let active = true;
    const params = new URLSearchParams(window.location.search);
    const checkoutState = params.get('checkout');
    const sessionId = params.get('session_id');
    if (checkoutState !== 'success' || !sessionId) {
      if (checkoutState === 'cancelled') {
        const cancelledNotice = t('creditPurchaseCancelled');
        queueMicrotask(() => {
          if (active) setCheckoutNotice(cancelledNotice);
        });
      }
      return () => {
        active = false;
      };
    }

    const reconcileCheckout = async () => {
      for (let attempt = 0; attempt < 6 && active; attempt += 1) {
        try {
          const status = await api.getCreditCheckoutStatus(sessionId);
          if (!active) return;
          setWallet(status.wallet);
          if (status.status === 'paid' || status.status === 'partially_refunded') {
            setCheckoutNotice(t('creditPurchaseSuccess', { count: status.credits }));
            setCheckoutContractAvailable(true);
            break;
          }
          if (status.status === 'failed') {
            setCheckoutNotice(t('creditPurchaseFailed'));
            break;
          }
          if (status.status === 'expired') {
            setCheckoutNotice(t('creditPurchaseExpired'));
            break;
          }
          setCheckoutNotice(t('creditPurchasePending'));
        } catch (checkoutError) {
          if (!active) return;
          setCheckoutNotice(
            checkoutError instanceof Error
              ? checkoutError.message
              : t('creditPurchaseStatusError'),
          );
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
      if (active) {
        const cleaned = new URL(window.location.href);
        cleaned.searchParams.delete('checkout');
        cleaned.searchParams.delete('session_id');
        window.history.replaceState({}, '', `${cleaned.pathname}${cleaned.search}${cleaned.hash}`);
      }
    };
    void reconcileCheckout();
    return () => {
      active = false;
    };
  }, [setWallet, t, user]);

  const handleProfileSave = useCallback(async (name: string, password?: string, confirmPassword?: string) => {
    if (!user) return;

    setAccountError('');
    setAccountMessage('');
    setAccountSaving(true);

    try {
      if (name && name !== user.name) {
        await api.updateProfile(name);
        await refreshUser();
        setAccountMessage(t('profileUpdated'));
      }

      if (user.provider === 'local' && (password || confirmPassword)) {
        if (password !== confirmPassword) {
          setAccountError(t('passwordsMismatch'));
          setAccountSaving(false);
          return;
        }
        await api.updatePassword(password!, confirmPassword!);
        setAccountMessage(t('passwordUpdated'));
      }
    } catch (err) {
      setAccountError(err instanceof Error ? err.message : t('accountUpdateError'));
    } finally {
      setAccountSaving(false);
    }
  }, [user, refreshUser, t]);

  // Memoized to prevent unnecessary re-renders of ProcessView and its children (JobListItem)
  const resetProcessing = useCallback(() => {
    activeUploadAbortRef.current?.abort();
    activeUploadAbortRef.current = null;
    setSelectedFile(null);
    setSelectedJob(null);
    setIsProcessing(false);
    setCanCancelProcessing(false);
    setProgress(0);
    setJobId(null);
    setStatusMessage('');
    setProcessError('');
    localStorage.removeItem('lastActiveJobId');
  }, [setSelectedJob]);

  // Memoized to prevent unnecessary re-renders of ProcessView and its children
  const handleFileSelect = useCallback((file: File | null) => {
    setSelectedFile(file);
    if (file) setSelectedJob(null);
  }, [setSelectedJob]);

  // Memoized to ensure stable reference for ProcessView -> JobListItem, preventing re-renders during progress updates
  const handleRefreshJobs = useCallback(async () => {
    await loadJobs(false);
  }, [loadJobs]);

  // Helper to open preview from history
  const handleShowPreview = useCallback((show: boolean) => {
    if (show) {
      setShowAccountPanel(false);
      // Scroll to top where player is
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, [setShowAccountPanel]);

  if (isLoading) {
    return (
      <div
        className="studio-loading-screen"
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <div className="studio-loading-content">
          <BrandLogo className="studio-loading-logo block h-auto" />
          <div className="studio-loading-wave" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
          <p>{t('loading')}</p>
        </div>
      </div>
    );
  }

  const hasBlockingModal = showAccountPanel
    || processingGateStage !== null
    || (paidCreditSalesUiApproved && showCreditPurchase);

  return (
    <div className="app-shell min-h-dvh relative overflow-x-hidden">
      <header
        className="studio-header"
        aria-label="gsubs studio"
        aria-hidden={hasBlockingModal || undefined}
        inert={hasBlockingModal ? true : undefined}
      >
        <Link href="/" className="studio-brand" aria-label={t('brandHomeLabel')}>
          <BrandLogo className="block h-auto w-[68px] sm:w-[80px]" />
        </Link>

        <div className="studio-header-account">
          <LanguageToggle />
          {user ? (
            <>
              <div className="studio-header-credits" data-testid="studio-header-credits">
                <CreditsBadge
                  onClick={
                    paidCreditSalesUiApproved
                      ? () => setShowCreditPurchase(true)
                      : undefined
                  }
                />
              </div>
              <button
                onClick={() => {
                  accountReturnFocusRef.current = document.activeElement instanceof HTMLElement
                    ? document.activeElement
                    : null;
                  setActiveAccountTab('profile');
                  setShowAccountPanel(!showAccountPanel);
                }}
                className="profile-trigger"
                aria-label={t('profileLabel')}
                title={t('accountSettingsTitle')}
              >
                <ProfileAvatar
                  name={user.name}
                  avatarUrl={user.avatar_url}
                />
              </button>
            </>
          ) : (
            <Link
              href="/login"
              className="guest-sign-in inline-flex min-h-10 items-center justify-center rounded-full border border-[var(--border-strong)] bg-white px-4 text-sm font-semibold text-[var(--foreground)] transition-colors hover:bg-[#f5f5f4]"
            >
              {t('guestSignIn')}
            </Link>
          )}
        </div>
      </header>

      <div
        className="studio-stage"
        aria-hidden={hasBlockingModal || undefined}
        inert={hasBlockingModal ? true : undefined}
      >
        <main
          className={`studio-main ${
            selectedJob?.status === 'completed' ? 'studio-main-workspace' : ''
          }`}
        >
          <section className="studio-intro" data-testid="studio-intro">
            <div className="studio-intro-copy">
              <h1>{t('heroTitle')}</h1>
              <p>{t('heroSubtitle')}</p>
            </div>
          </section>

          {checkoutNotice && (
            <div
              role="status"
              className="mb-5 flex items-center justify-between gap-4 rounded-2xl border border-sky-400/20 bg-sky-400/[0.07] px-4 py-3 text-sm text-[var(--foreground)]"
            >
              <span>{checkoutNotice}</span>
              {checkoutContractAvailable && (
                <Link
                  href="/account/billing"
                  className="font-semibold text-[var(--accent)] underline underline-offset-4"
                >
                  {t('billingContractDownload')}
                </Link>
              )}
              <button
                type="button"
                onClick={() => setCheckoutNotice('')}
                className="grid h-8 w-8 place-items-center rounded-full text-[var(--muted)] hover:bg-white/5 hover:text-[var(--foreground)]"
                aria-label={t('closeLabel')}
              >
                ✕
              </button>
            </div>
          )}

          <ProcessView
            selectedFile={selectedFile}
            onFileSelect={handleFileSelect}
            isProcessing={isProcessing}
            progress={progress}
            statusMessage={statusMessage}
            error={processError}
            onStartProcessing={requestStartProcessing}
            onReprocessJob={requestReprocessJob}
            onReset={resetProcessing}
            onCancelProcessing={canCancelProcessing ? handleCancelProcessing : undefined}
            selectedJob={selectedJob}
            onJobSelect={setSelectedJob}
            onRefreshJobs={refreshActivity}
            statusStyles={statusStyles}
            buildStaticUrl={buildStaticUrl}
            totalJobs={totalJobs}
          />
        </main>

        <footer className="studio-footer">
          <a href="https://ascentia-gp.com/" target="_blank" rel="noopener noreferrer" className="footer-brand">
            <BrandLogo className="block h-auto w-[68px]" />
            <span><small>by Ascentia</small></span>
          </a>
          <div className="footer-links">
            <a href="/privacy">{t('cookieLearnMore') || 'Privacy Policy'}</a>
            <a href="/terms">{t('cookieTerms') || 'Terms of Service'}</a>
          </div>
        </footer>
      </div>

      {processingGateStage !== null && !showCreditPurchase && (
        <ProcessingGateModal
          isOpen
          stage={processingGateStage}
          cost={pendingProcessingCost}
          balance={processingGateBalance}
          requiresPaidCredits={pendingProcessingRequiresPaidCredits}
          isBalanceLoading={isGateBalanceLoading}
          error={processingGateError}
          onClose={closeProcessingGate}
          onAuthenticated={handleGateAuthenticated}
          onConfirm={handleGateConfirm}
          onPurchaseCredits={
            paidCreditSalesUiApproved
              ? () => setShowCreditPurchase(true)
              : undefined
          }
        />
      )}

      {paidCreditSalesUiApproved && (
        <CreditPurchaseDialog
          isOpen={showCreditPurchase}
          isAuthenticated={Boolean(user)}
          requiredCredits={pendingProcessingCost}
          onClose={closeCreditPurchase}
          onRequireAuth={() => {
            setShowCreditPurchase(false);
            setProcessingGateStage('auth');
          }}
        />
      )}

      {user && showAccountPanel && (
        <div className="fixed inset-0 z-50 flex items-end justify-center px-4 pt-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] sm:items-start sm:pt-20">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={handleCloseAccountPanel}
          />
          <div
            ref={accountDialogRef}
            className="relative z-10 w-full max-w-2xl animate-fade-in"
            role="dialog"
            aria-modal="true"
            aria-label={activeAccountTab === 'profile' ? t('accountSettingsTitle') : t('historyTitle')}
            tabIndex={-1}
          >
            <div className="bg-[var(--surface-elevated)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden max-h-[90dvh] sm:max-h-[85dvh] flex flex-col">
              <div className="flex items-center justify-between gap-1 p-4 border-b border-[var(--border)] sm:gap-3">
                <div className="flex min-w-0 flex-1 items-center gap-1 sm:gap-4">
                  <button
                    onClick={() => setActiveAccountTab('profile')}
                    className={`min-h-11 min-w-0 px-1 text-xs font-semibold border-b-2 transition-colors sm:text-sm ${activeAccountTab === 'profile' ? 'border-[var(--accent)] text-[var(--accent)]' : 'border-transparent text-[var(--muted)] hover:text-[var(--foreground)]'}`}
                  >
                    {t('accountSettingsTitle')}
                  </button>
                  <button
                    onClick={() => setActiveAccountTab('history')}
                    className={`min-h-11 min-w-0 px-1 text-xs font-semibold border-b-2 transition-colors sm:text-sm ${activeAccountTab === 'history' ? 'border-[var(--accent)] text-[var(--accent)]' : 'border-transparent text-[var(--muted)] hover:text-[var(--foreground)]'}`}
                  >
                    {t('historyTitle') || 'History'}
                  </button>
                </div>
                <button
                  ref={accountCloseButtonRef}
                  onClick={handleCloseAccountPanel}
                  className="flex min-h-11 min-w-11 flex-none items-center justify-center rounded-lg transition-colors hover:bg-black/5"
                  aria-label={t('closeLabel')}
                >
                  <span aria-hidden="true">✕</span>
                </button>
              </div>
              <div className="p-4 overflow-y-auto">
                <AccountView
                  user={user}
                  onSaveProfile={handleProfileSave}
                  onLogout={handleLogout}
                  accountMessage={accountMessage}
                  accountError={accountError}
                  accountSaving={accountSaving}
                  activeTab={activeAccountTab}
                  // History props
                  recentJobs={recentJobs}
                  jobsLoading={jobsLoading}
                  onJobSelect={setSelectedJob}
                  selectedJobId={selectedJob?.id}
                  onRefreshJobs={handleRefreshJobs}
                  formatDate={formatDate}
                  buildStaticUrl={buildStaticUrl}
                  setShowPreview={handleShowPreview}
                  currentPage={currentPage}
                  totalPages={totalPages}
                  onNextPage={nextPage}
                  onPrevPage={prevPage}
                  totalJobs={totalJobs}
                  pageSize={pageSize}
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
