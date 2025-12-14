'use client';

import { useCallback, useEffect, useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { api, JobResponse } from '@/lib/api';
import { formatDate, buildStaticUrl } from '@/lib/utils';
import { useI18n } from '@/context/I18nContext';
import { LanguageToggle } from '@/components/LanguageToggle';
import { ProcessView, ProcessingOptions } from '@/components/ProcessView';
import { AccountView } from '@/components/AccountView';
import { useJobs } from '@/hooks/useJobs';
import { useJobPolling, JobPollingCallbacks } from '@/hooks/useJobPolling';

const statusStyles: Record<string, string> = {
  completed: 'bg-green-500/15 text-green-300 border-green-500/30',
  processing: 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/40',
  pending: 'bg-[var(--muted)]/10 text-[var(--muted)] border-[var(--border)]',
  failed: 'bg-[var(--danger)]/15 text-[var(--danger)] border-[var(--danger)]/40',
};

export default function DashboardPage() {
  const { user, isLoading, logout, refreshUser } = useAuth();
  const router = useRouter();
  const { t } = useI18n();

  // Handler functions (extracted for testability)
  /* istanbul ignore next -- browser reload not testable in JSDOM */
  const handleReloadPage = useCallback(() => {
    window.location.reload();
  }, []);

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

  // Account Modal State
  const [showAccountPanel, setShowAccountPanel] = useState(false);
  const [activeAccountTab, setActiveAccountTab] = useState<'profile' | 'history'>('profile');
  const [accountMessage, setAccountMessage] = useState('');
  const [accountError, setAccountError] = useState('');
  const [accountSaving, setAccountSaving] = useState(false);

  useEffect(() => {
    if (!isLoading && !user) {
      router.push('/login');
    }
  }, [user, isLoading, router]);

  // Refresh data
  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

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
      setProcessError('Processing cancelled');
      refreshActivity();
    } catch (err) {
      // If cancel fails, just continue polling
      console.error('Cancel failed:', err);
    }
  }, [jobId, refreshActivity]);

  // Use the polling hook
  useJobPolling({
    jobId,
    callbacks: pollingCallbacks,
    t: t as (key: string) => string,
  });

  const handleStartProcessing = useCallback(async (options: ProcessingOptions) => {
    if (!selectedFile) return;

    setIsProcessing(true);
    setProcessError('');
    setProgress(0);
    setSelectedJob(null);
    setStatusMessage(t('statusUploading'));

    const modelMap: Record<string, string> = {
      fast: 'tiny',
      balanced: 'medium',
      turbo: 'turbo', // Backend maps 'turbo' -> large-v3 for maximum accuracy
      best: 'large-v3',
    };

    const provider = options.transcribeProvider;
    // Robustly handle OpenAI model selection: Always use whisper-1 regardless of current transcribeMode
    // This fixes the issue where having 'turbo' selected then switching to OpenAI resulted in undefined model mapping
    const selectedModel = provider === 'openai' ? 'openai/whisper-1' : modelMap[options.transcribeMode];

    try {
      const result = await api.processVideo(selectedFile, {
        transcribe_model: selectedModel,
        transcribe_provider: provider,
        openai_model: provider === 'openai' ? selectedModel.replace('openai/', '') : undefined,
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
      });
      setJobId(result.id);
    } catch (err) {
      setProcessError(err instanceof Error ? err.message : t('startProcessingError'));
      setIsProcessing(false);
    }
  }, [selectedFile, t, setSelectedJob]);

  const handleProfileSave = async (name: string, password?: string, confirmPassword?: string) => {
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
  };

  // Memoized to prevent unnecessary re-renders of ProcessView and its children (JobListItem)
  const resetProcessing = useCallback(() => {
    setSelectedFile(null);
    setSelectedJob(null);
    setProgress(0);
    setJobId(null);
    setStatusMessage('');
    setProcessError('');
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
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-[var(--muted)]">{t('loading')}</div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="min-h-screen relative overflow-hidden">
      <div className="pointer-events-none absolute -left-16 -top-10 h-80 w-80 rounded-full bg-[var(--accent)]/12 blur-3xl" />
      <div className="pointer-events-none absolute right-4 top-40 h-72 w-72 rounded-full bg-[var(--accent-secondary)]/14 blur-3xl" />
      <div className="pointer-events-none absolute -right-10 bottom-0 h-96 w-96 rounded-full bg-[#6aa4ff]/10 blur-3xl" />

      <nav className="sticky top-0 z-20 backdrop-blur-2xl bg-[var(--background)]/75 border-b border-[var(--border)]/60 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
          {/* Left spacer for centering */}
          <div className="flex-1" />

          {/* Centered Logo */}
          <button
            onClick={handleReloadPage}
            className="flex items-center justify-center -my-4 rounded-xl transition-all duration-300 cursor-pointer group hover:scale-105"
            aria-label="Reload page"
          >
            <div className="relative">
              <div className="absolute inset-0 -m-6 bg-[var(--accent)]/15 blur-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-full" />
              <img
                src="/ascentia-subs.png"
                alt="Ascentia Subs"
                className="relative h-24 w-auto object-contain drop-shadow-[0_4px_20px_rgba(0,0,0,0.5)] group-hover:drop-shadow-[0_0_30px_rgba(141,247,223,0.6)] transition-all duration-300"
              />
            </div>
          </button>

          {/* Right: Profile Icon Only */}
          <div className="flex-1 flex justify-end">
            <button
              onClick={() => {
                setActiveAccountTab('profile');
                setShowAccountPanel(!showAccountPanel);
              }}
              className="h-12 w-12 rounded-full bg-white/5 border border-[var(--border)] hover:bg-white/10 hover:border-[var(--accent)]/50 transition-all cursor-pointer flex items-center justify-center text-xl"
              aria-label={t('accountSettingsTitle')}
            >
              👤
            </button>
          </div>
        </div>
      </nav>

      <main className="relative max-w-6xl mx-auto px-6 py-10 space-y-8">
        <section className="card border-[var(--border)]/70 bg-white/[0.02] flex flex-col gap-8">
          <div className="space-y-4 w-full">
            <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)]/70 bg-white/[0.03] px-3 py-1 text-xs uppercase tracking-[0.3em] text-[var(--muted)]">
              <span className="h-2 w-2 rounded-full bg-[var(--accent)] shadow-[0_0_0_3px_rgba(141,247,223,0.25)]" />
              {t('brandBadge')}
            </div>
            <h1 className="text-4xl lg:text-5xl font-semibold leading-tight">
              {t('heroTitle')}
            </h1>
            <p className="text-[var(--muted)] text-lg">
              {t('heroSubtitle')}
            </p>
          </div>

          {/* Tab Navigation Removed */}
        </section>

        <ProcessView
          selectedFile={selectedFile}
          onFileSelect={handleFileSelect}
          isProcessing={isProcessing}
          progress={progress}
          statusMessage={statusMessage}
          error={processError}
          onStartProcessing={handleStartProcessing}
          onReset={resetProcessing}
          onCancelProcessing={handleCancelProcessing}
          selectedJob={selectedJob}
          onJobSelect={setSelectedJob}
          statusStyles={statusStyles}
          buildStaticUrl={buildStaticUrl}
        />
      </main>

      {/* Ascentia Branding */}
      <footer className="relative z-10 mt-16 pb-8">
        <div className="max-w-6xl mx-auto px-6">
          <div className="flex flex-col items-center justify-center gap-4 py-8 border-t border-[var(--border)]/40">
            <a
              href="https://ascentia-gp.com/"
              target="_blank"
              rel="noopener noreferrer"
              className="group flex flex-col items-center gap-3 transition-all duration-300 hover:scale-105"
            >
              <div className="relative">
                <div className="absolute inset-0 rounded-full bg-[var(--accent)]/20 blur-xl opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                <img
                  src="/ascentia-logo.png"
                  alt="Ascentia Logo"
                  className="relative h-16 w-auto object-contain drop-shadow-lg group-hover:drop-shadow-[0_0_15px_rgba(141,247,223,0.4)] transition-all duration-300"
                />
              </div>
              <div className="text-center">
                <p className="text-xs uppercase tracking-[0.3em] text-[var(--muted)] group-hover:text-[var(--foreground)] transition-colors duration-300">
                  Brought to you by
                </p>
                <p className="text-lg font-semibold bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] bg-clip-text text-transparent group-hover:opacity-90 transition-opacity">
                  Ascentia
                </p>
              </div>
            </a>
          </div>
        </div>
      </footer>

      {/* Language Toggle */}
      <div className="fixed bottom-4 right-4 z-20">
        <LanguageToggle />
      </div>

      {showAccountPanel && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={handleCloseAccountPanel}
          />
          <div className="relative z-10 w-full max-w-2xl animate-fade-in">
            <div className="bg-[var(--surface-elevated)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden max-h-[85vh] flex flex-col">
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
