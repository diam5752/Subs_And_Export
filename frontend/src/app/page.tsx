'use client';

import { useCallback, useEffect, useState, useMemo, useRef } from 'react';
import { useAuth } from '@/context/AuthContext';
import { useAppEnv } from '@/context/AppEnvContext';
import { usePoints } from '@/context/PointsContext';
import { api, JobResponse } from '@/lib/api';
import { formatDate, buildStaticUrl } from '@/lib/utils';
import { useI18n } from '@/context/I18nContext';
import { LanguageToggle } from '@/components/LanguageToggle';
import { ProcessView, ProcessingOptions } from '@/features/process/ProcessView';
import { AccountView } from '@/components/AccountView';
import { CreditsBadge } from '@/components/CreditsBadge';
import { ProcessingGateModal, type ProcessingGateStage } from '@/components/ProcessingGateModal';
import { useJobs } from '@/hooks/useJobs';
import { useJobPolling, JobPollingCallbacks } from '@/hooks/useJobPolling';
import { processVideoCostForSelection } from '@/lib/points';
import Link from 'next/link';

const statusStyles: Record<string, string> = {
  completed: 'bg-green-500/15 text-green-300 border-green-500/30',
  processing: 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/40',
  pending: 'bg-[var(--muted)]/10 text-[var(--muted)] border-[var(--border)]',
  failed: 'bg-[var(--danger)]/15 text-[var(--danger)] border-[var(--danger)]/40',
};

type PendingProcessingAction =
  | { kind: 'new'; options: ProcessingOptions }
  | { kind: 'reprocess'; sourceJobId: string; options: ProcessingOptions };

export default function DashboardPage() {
  const { user, isLoading, logout, refreshUser } = useAuth();
  const { balance, setBalance: setPointsBalance, refreshBalance } = usePoints();
  const { t } = useI18n();
  const { appEnv } = useAppEnv();
  const didRestoreSession = useRef(false);

  const handleCloseAccountPanel = useCallback(() => {
    setShowAccountPanel(false);
  }, []);



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
  const [pendingProcessingAction, setPendingProcessingAction] = useState<PendingProcessingAction | null>(null);
  const [processingGateStage, setProcessingGateStage] = useState<ProcessingGateStage | null>(null);
  const [processingGateError, setProcessingGateError] = useState('');
  const [isGateBalanceLoading, setIsGateBalanceLoading] = useState(false);

  // Account Modal State
  const [showAccountPanel, setShowAccountPanel] = useState(false);
  const [activeAccountTab, setActiveAccountTab] = useState<'profile' | 'history'>('profile');
  const [accountMessage, setAccountMessage] = useState('');
  const [accountError, setAccountError] = useState('');
  const [accountSaving, setAccountSaving] = useState(false);

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

          // A completed job whose local artifacts were cleaned up cannot render
          // a preview or transcript, so it must not reopen as a broken editor.
          if (job.status !== 'failed' && completedFilesAreAvailable) {
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
  }, [jobId, selectedFile, selectedJob, setSelectedJob, user]);

  // Persist session
  useEffect(() => {
    if (selectedJob?.id) {
      localStorage.setItem('lastActiveJobId', selectedJob.id);
    }
  }, [selectedJob]);

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
      setJobId(null);
      setSelectedJob(job);
      setProcessError('');
      refreshActivity();
    },
    onFailed: (errorMessage: string) => {
      setProcessError(errorMessage);
      setIsProcessing(false);
      setJobId(null);
      refreshActivity();
    },
    onError: (errorMessage: string) => {
      setIsProcessing(false);
      setProcessError(errorMessage);
    },
  }), [refreshActivity, setSelectedJob]);

  // Cancel processing handler
  const handleCancelProcessing = useCallback(async () => {
    if (!jobId) return;
    try {
      await api.cancelJob(jobId);
      setIsProcessing(false);
      setJobId(null);
      setProcessError(t('processingCancelled'));
      refreshActivity();
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

    setIsProcessing(true);
    setProcessError('');
    setProgress(0);
    setSelectedJob(null);
    setStatusMessage(t('statusUploading'));

    const provider = options.transcribeProvider || 'mock';
    const selectedModel = options.transcribeMode || 'standard';

    try {
      const settings = {
        transcribe_model: selectedModel,
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

      // Mock processing is deliberately local-only, including in production.
      // GCS is reserved for real providers so a mock deployment never depends
      // on (or accidentally sends media to) an external storage service.
      const result = appEnv === 'production' && provider !== 'mock'
        ? await (async () => {
          const upload = await api.createGcsUploadUrl(selectedFile);
          setStatusMessage(t('statusUploading'));
          setProgress(0);
          await api.uploadToSignedUrl(
            upload.upload_url,
            selectedFile,
            upload.required_headers['Content-Type'],
            (percent) => {
              setProgress(percent);
              setStatusMessage(`${t('statusUploading')} ${percent}%`);
            },
          );
          setStatusMessage(t('statusProcessing'));
          setProgress(0);
          return api.processVideoFromGcs(upload.upload_id, settings);
        })()
        : await api.processVideo(selectedFile, settings);
      setJobId(result.id);
      if (typeof result.balance === 'number') {
        setPointsBalance(result.balance);
      } else {
        void refreshBalance();
      }
    } catch (err) {
      setProcessError(err instanceof Error ? err.message : t('startProcessingError'));
      setIsProcessing(false);
    }
  }, [appEnv, refreshBalance, selectedFile, setPointsBalance, t, setSelectedJob]);

  const executeReprocessJob = useCallback(async (sourceJobId: string, options: ProcessingOptions) => {
    setIsProcessing(true);
    setProcessError('');
    setProgress(0);
    setStatusMessage(t('statusProcessing'));

    const provider = options.transcribeProvider || 'mock';
    const selectedModel = options.transcribeMode || 'standard';

    try {
      const settings = {
        transcribe_model: selectedModel,
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
      if (typeof result.balance === 'number') {
        setPointsBalance(result.balance);
      } else {
        void refreshBalance();
      }
    } catch (err) {
      setProcessError(err instanceof Error ? err.message : t('startProcessingError'));
      setIsProcessing(false);
    }
  }, [refreshBalance, setPointsBalance, t]);

  const pendingProcessingCost = useMemo(() => {
    if (!pendingProcessingAction) return 0;
    return processVideoCostForSelection(
      pendingProcessingAction.options.transcribeProvider,
      pendingProcessingAction.options.transcribeMode,
    );
  }, [pendingProcessingAction]);

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
      setPointsBalance(points.balance);
    } catch (err) {
      setProcessingGateError(err instanceof Error ? err.message : t('creditsError'));
    } finally {
      setIsGateBalanceLoading(false);
    }
  }, [setPointsBalance, t]);

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
    if (!pendingProcessingAction || balance === null || balance < pendingProcessingCost) return;

    const action = pendingProcessingAction;
    closeProcessingGate();
    if (action.kind === 'new') {
      await executeStartProcessing(action.options);
      return;
    }
    await executeReprocessJob(action.sourceJobId, action.options);
  }, [
    balance,
    closeProcessingGate,
    executeReprocessJob,
    executeStartProcessing,
    pendingProcessingAction,
    pendingProcessingCost,
  ]);

  const openOptionalSignIn = useCallback(() => {
    setPendingProcessingAction(null);
    setProcessingGateError('');
    setProcessingGateStage('auth');
  }, []);

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
    setSelectedFile(null);
    setSelectedJob(null);
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
  }, []);

  if (isLoading) {
    return (
      <div className="min-h-dvh flex items-center justify-center">
        <div className="text-[var(--muted)]">{t('loading')}</div>
      </div>
    );
  }

  const hasBlockingModal = showAccountPanel || processingGateStage !== null;

  return (
    <div className="app-shell min-h-dvh relative overflow-x-hidden">
      <header
        className="studio-header"
        aria-label="Subframe studio"
        aria-hidden={hasBlockingModal || undefined}
        inert={hasBlockingModal ? true : undefined}
      >
        <Link href="/" className="studio-brand" aria-label={t('brandHomeLabel')}>
          <strong>SUBFRAME</strong>
        </Link>

        <nav className="studio-nav" aria-label="Workspace navigation">
          {user && (
            <button
              type="button"
              className="studio-nav-item"
              onClick={() => {
                setActiveAccountTab('history');
                setShowAccountPanel(true);
              }}
            >
              <span>{t('historyTitle') || 'History'}</span>
            </button>
          )}
        </nav>

        <div className="studio-header-account">
          {user ? (
            <>
              <div className="studio-header-credits" data-testid="studio-header-credits">
                <CreditsBadge />
              </div>
              <button
                onClick={() => {
                  setActiveAccountTab('profile');
                  setShowAccountPanel(!showAccountPanel);
                }}
                className="profile-trigger"
                aria-label={t('profileLabel')}
                title={t('accountSettingsTitle')}
              >
                {user.name?.trim().charAt(0).toUpperCase() || 'A'}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={openOptionalSignIn}
              className="min-h-10 rounded-full border border-[var(--border-strong)] bg-white px-4 text-sm font-semibold text-[var(--foreground)] transition-colors hover:bg-[#f5f5f4]"
            >
              {t('guestSignIn')}
            </button>
          )}
        </div>
      </header>

      <div
        className="studio-stage"
        aria-hidden={hasBlockingModal || undefined}
        inert={hasBlockingModal ? true : undefined}
      >
        <main className="studio-main">
          <section className="studio-intro" data-testid="studio-intro">
            <div className="studio-intro-copy">
              <h1>{t('heroTitle')}</h1>
              <p>{t('heroSubtitle')}</p>
            </div>
          </section>

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
            onCancelProcessing={handleCancelProcessing}
            selectedJob={selectedJob}
            onJobSelect={setSelectedJob}
            statusStyles={statusStyles}
            buildStaticUrl={buildStaticUrl}
            totalJobs={totalJobs}
          />
        </main>

        <footer className="studio-footer">
          <a href="https://ascentia-gp.com/" target="_blank" rel="noopener noreferrer" className="footer-brand">
            <span><strong>ASCENTIA</strong><small>Built for creators</small></span>
          </a>
          <div className="footer-links">
            <a href="/privacy">{t('cookieLearnMore') || 'Privacy Policy'}</a>
            <a href="/terms">{t('cookieTerms') || 'Terms of Service'}</a>
          </div>
        </footer>
      </div>

      {!hasBlockingModal && (
        <div className="fixed bottom-[calc(env(safe-area-inset-bottom)+1rem)] right-[calc(env(safe-area-inset-right)+1rem)] z-20">
          <LanguageToggle />
        </div>
      )}

      <ProcessingGateModal
        isOpen={processingGateStage !== null}
        stage={processingGateStage ?? 'auth'}
        cost={pendingProcessingCost}
        balance={balance}
        isBalanceLoading={isGateBalanceLoading}
        error={processingGateError}
        onClose={closeProcessingGate}
        onAuthenticated={handleGateAuthenticated}
        onConfirm={handleGateConfirm}
      />

      {user && showAccountPanel && (
        <div className="fixed inset-0 z-50 flex items-end justify-center px-4 pt-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] sm:items-start sm:pt-20">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={handleCloseAccountPanel}
          />
          <div className="relative z-10 w-full max-w-2xl animate-fade-in">
            <div className="bg-[var(--surface-elevated)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden max-h-[90dvh] sm:max-h-[85dvh] flex flex-col">
              <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
                <div className="flex gap-4">
                  <button
                    onClick={() => setActiveAccountTab('profile')}
                    className={`text-sm font-semibold pb-1 border-b-2 transition-colors ${activeAccountTab === 'profile' ? 'border-[var(--accent)] text-[var(--accent)]' : 'border-transparent text-[var(--muted)] hover:text-[var(--foreground)]'}`}
                  >
                    {t('accountSettingsTitle')}
                  </button>
                  <button
                    onClick={() => setActiveAccountTab('history')}
                    className={`text-sm font-semibold pb-1 border-b-2 transition-colors ${activeAccountTab === 'history' ? 'border-[var(--accent)] text-[var(--accent)]' : 'border-transparent text-[var(--muted)] hover:text-[var(--foreground)]'}`}
                  >
                    {t('historyTitle') || 'History'}
                  </button>
                </div>
                <button
                  onClick={handleCloseAccountPanel}
                  className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                >
                  ✕
                </button>
              </div>
              <div className="p-4 overflow-y-auto">
                <AccountView
                  user={user}
                  onSaveProfile={handleProfileSave}
                  onLogout={logout}
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
