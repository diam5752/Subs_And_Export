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

  // Use the polling hook
  useJobPolling({
    jobId,
    callbacks: pollingCallbacks,
    t: t as (key: string) => string,
  });

  const handleStartProcessing = async (options: ProcessingOptions) => {
    if (!selectedFile) return;

    setIsProcessing(true);
    setProcessError('');
    setProgress(0);
    setSelectedJob(null);
    setStatusMessage(t('statusUploading'));

    const modelMap: Record<string, string> = {
      fast: 'tiny',
      balanced: 'medium',
      turbo: 'deepdml/faster-whisper-large-v3-turbo-ct2',
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
      });
      setJobId(result.id);
    } catch (err) {
      setProcessError(err instanceof Error ? err.message : t('startProcessingError'));
      setIsProcessing(false);
    }
  };

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

  const resetProcessing = () => {
    setSelectedFile(null);
    setSelectedJob(null);
    setProgress(0);
    setJobId(null);
    setStatusMessage('');
    setProcessError('');
  };

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
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <button
              onClick={() => setShowAccountPanel(!showAccountPanel)}
              className="px-3 py-2 rounded-xl bg-white/5 border border-[var(--border)] hover:bg-white/10 hover:border-[var(--accent)]/50 transition-all cursor-pointer text-left flex items-center gap-3"
              aria-label={t('accountSettingsTitle')}
            >
              <span
                className="h-10 w-10 rounded-full bg-white/10 border border-[var(--border)] flex items-center justify-center text-lg shadow-inner"
                aria-hidden="true"
              >
                👤
              </span>
              <div className="min-w-0 hidden sm:block">
                <div className="font-semibold text-sm truncate">{user.name}</div>
                <div className="text-[var(--muted)] text-xs uppercase tracking-wide">
                  {t('sessionLabelProvider').replace('{provider}', user.provider)}
                </div>
              </div>
            </button>
          </div>

          <button
            onClick={handleReloadPage}
            className="flex items-center gap-3 justify-center px-4 py-2 rounded-xl hover:bg-white/10 transition-all duration-200 cursor-pointer group"
            aria-label="Reload page"
          >
            <div className="h-11 w-11 rounded-2xl bg-white/5 border border-[var(--border)] flex items-center justify-center text-xl shadow-inner group-hover:bg-white/10 transition-colors">🎛️</div>
            <div className="text-center hidden sm:block">
              <p className="text-[var(--muted)] text-xs uppercase tracking-[0.35em] group-hover:text-[var(--foreground)] transition-colors">{t('subtitleDesk')}</p>
              <p className="text-xl font-semibold leading-tight group-hover:text-[var(--accent)] transition-colors">{t('brandName')}</p>
            </div>
          </button>

          <div className="flex items-center gap-3 justify-end flex-1">
            <button onClick={logout} className="btn-secondary text-sm py-2 px-4">
              {t('signOut')}
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
          onFileSelect={(file) => {
            setSelectedFile(file);
            if (file) setSelectedJob(null);
          }}
          isProcessing={isProcessing}
          progress={progress}
          statusMessage={statusMessage}
          error={processError}
          onStartProcessing={handleStartProcessing}
          onReset={resetProcessing}
          selectedJob={selectedJob}
          onJobSelect={setSelectedJob}
          recentJobs={recentJobs}
          jobsLoading={jobsLoading}
          statusStyles={statusStyles}
          formatDate={formatDate}
          buildStaticUrl={buildStaticUrl}
          onRefreshJobs={async () => { await loadJobs(false); }}
          currentPage={currentPage}
          totalPages={totalPages}
          onNextPage={nextPage}
          onPrevPage={prevPage}
        />
      </main>

      <footer className="fixed bottom-4 right-4 z-20">
        <LanguageToggle />
      </footer>

      {showAccountPanel && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={handleCloseAccountPanel}
          />
          <div className="relative z-10 w-full max-w-2xl animate-fade-in">
            <div className="bg-[var(--surface-elevated)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden">
              <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
                <h2 className="text-lg font-semibold">{t('accountSettingsTitle')}</h2>
                <button
                  onClick={handleCloseAccountPanel}
                  className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                >
                  ✕
                </button>
              </div>
              <div className="p-4 max-h-[70vh] overflow-y-auto">
                <AccountView
                  user={user}
                  onSaveProfile={handleProfileSave}
                  accountMessage={accountMessage}
                  accountError={accountError}
                  accountSaving={accountSaving}
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
