'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { api, API_BASE, JobResponse, HistoryEvent } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';
import { LanguageToggle } from '@/components/LanguageToggle';
import { ProcessView, ProcessingOptions } from '@/components/ProcessView';
import { HistoryView } from '@/components/HistoryView';
import { AccountView } from '@/components/AccountView';

// type TabKey = 'process' | 'history' | 'account'; // Removed

const statusStyles: Record<string, string> = {
  completed: 'bg-green-500/15 text-green-300 border-green-500/30',
  processing: 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/40',
  pending: 'bg-[var(--muted)]/10 text-[var(--muted)] border-[var(--border)]',
  failed: 'bg-[var(--danger)]/15 text-[var(--danger)] border-[var(--danger)]/40',
};

function formatDate(ts: string | number): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.toString();
  return d.toLocaleString();
}

function buildStaticUrl(path?: string | null): string | null {
  if (!path) return null;
  const cleaned = path.replace(/^https?:\/\/[^/]+/i, '');
  const withPrefix = cleaned.startsWith('/static/')
    ? cleaned
    : `/static/${cleaned.replace(/^\/?data\//, '').replace(/^\/?static\//, '')}`;
  return `${API_BASE}${withPrefix}`;
}

export default function DashboardPage() {
  const { user, isLoading, logout, refreshUser } = useAuth();
  const router = useRouter();
  const { t } = useI18n();

  // const [activeTab, setActiveTab] = useState<TabKey>('process'); // Removed

  // Job / Process State (Managed here to persist across tabs if needed, though simpler now)
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState('');

  const [selectedJob, setSelectedJob] = useState<JobResponse | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobResponse[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);

  const [historyItems, setHistoryItems] = useState<HistoryEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');

  const [accountMessage, setAccountMessage] = useState('');
  const [accountError, setAccountError] = useState('');
  const [accountSaving, setAccountSaving] = useState(false);

  useEffect(() => {
    if (!isLoading && !user) {
      router.push('/login');
    }
  }, [user, isLoading, router]);

  const loadJobs = useCallback(async () => {
    if (!user) return;
    setJobsLoading(true);
    try {
      const jobs = await api.getJobs();
      const sorted = [...jobs].sort(
        (a, b) => (b.updated_at || b.created_at) - (a.updated_at || a.created_at)
      );
      setRecentJobs(sorted);
      const latest = sorted.find((job) => job.status === 'completed' && job.result_data);
      // Only auto-select if we don't have a file staged and don't have a job selected
      if (latest && !selectedJob && !selectedFile) {
        setSelectedJob(latest);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('jobsErrorFallback'));
    } finally {
      setJobsLoading(false);
    }
  }, [user, selectedJob, t]);

  const loadHistory = useCallback(async () => {
    if (!user) return;
    setHistoryLoading(true);
    setHistoryError('');
    try {
      const data = await api.getHistory(50);
      setHistoryItems(data);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : t('historyErrorFallback'));
    } finally {
      setHistoryLoading(false);
    }
  }, [user, t]);

  const refreshActivity = useCallback(async () => {
    await loadJobs();
    await loadHistory();
  }, [loadJobs, loadHistory]);

  useEffect(() => {
    if (!user || isLoading) return;
    loadJobs();
    // if (activeTab !== 'process') {
    //   loadHistory();
    // }
  }, [user, isLoading, loadJobs]);

  // Polling for job status
  useEffect(() => {
    if (!jobId) return;

    const pollInterval = setInterval(async () => {
      try {
        const job = await api.getJobStatus(jobId);
        setProgress(job.progress);
        setStatusMessage(job.message || (job.status === 'processing' ? t('statusProcessingEllipsis') : ''));

        if (job.status === 'completed') {
          setIsProcessing(false);
          setJobId(null);
          setSelectedJob(job);
          setError('');
          clearInterval(pollInterval);
          refreshActivity();
        } else if (job.status === 'failed') {
          setError(job.message || t('statusFailedFallback'));
          setIsProcessing(false);
          setJobId(null);
          clearInterval(pollInterval);
          refreshActivity();
        }
      } catch {
        clearInterval(pollInterval);
        setIsProcessing(false);
        setError(t('statusCheckFailed'));
      }
    }, 1000);

    return () => clearInterval(pollInterval);
  }, [jobId, refreshActivity, t]);

  const handleStartProcessing = async (options: ProcessingOptions) => {
    if (!selectedFile) return;

    setIsProcessing(true);
    setError('');
    setProgress(0);
    setSelectedJob(null);
    setStatusMessage(t('statusUploading'));

    const modelMap: Record<string, string> = {
      fast: 'tiny',
      balanced: 'medium',
      turbo: 'deepdml/faster-whisper-large-v3-turbo-ct2',
      best: 'large-v3',
    };
    const hostedModel = 'openai/gpt-4o-mini-transcribe';
    const provider = options.transcribeProvider;
    const selectedModel = provider === 'openai' ? hostedModel : modelMap[options.transcribeMode];

    try {
      const result = await api.processVideo(selectedFile, {
        transcribe_model: selectedModel,
        transcribe_provider: provider,
        openai_model: provider === 'openai' ? hostedModel : undefined,
        video_quality: options.outputQuality,
        use_llm: options.useAI,
        context_prompt: options.contextPrompt,
      });
      setJobId(result.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('startProcessingError'));
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
    setProgress(0);
    setJobId(null);
    setStatusMessage('');
    setError('');
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
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-11 w-11 rounded-2xl bg-white/5 border border-[var(--border)] flex items-center justify-center text-xl shadow-inner">🎛️</div>
            <div>
              <p className="text-[var(--muted)] text-xs uppercase tracking-[0.35em]">{t('subtitleDesk')}</p>
              <p className="text-xl font-semibold leading-tight">{t('brandName')}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 justify-end min-w-0">
            <LanguageToggle />
            {/* Tabs removed */}
            <div className="hidden md:block h-8 w-px bg-[var(--border)]" />
            <div className="flex items-center gap-3 text-sm min-w-[230px]">
              <div className="px-3 py-2 rounded-xl bg-white/5 border border-[var(--border)] min-w-[170px]">
                <div className="font-semibold truncate">{user.name}</div>
                <div className="text-[var(--muted)] text-xs uppercase tracking-wide">
                  {t('sessionLabelProvider').replace('{provider}', user.provider)}
                </div>
              </div>
              <button onClick={logout} className="btn-secondary text-sm py-2 px-4">
                {t('signOut')}
              </button>
            </div>
          </div>
        </div>
      </nav>

      <main className="relative max-w-6xl mx-auto px-6 py-10 space-y-8">
        <section className="card border-[var(--border)]/70 bg-white/[0.02] flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-4 max-w-2xl">
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
          error={error}
          onStartProcessing={handleStartProcessing}
          onReset={resetProcessing}
          selectedJob={selectedJob}
          onJobSelect={setSelectedJob}
          recentJobs={recentJobs}
          jobsLoading={jobsLoading}
          statusStyles={statusStyles}
          formatDate={formatDate}
          buildStaticUrl={buildStaticUrl}
        />
      </main>
    </div>
  );
}
