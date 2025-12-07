'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { api, API_BASE, JobResponse, HistoryEvent } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';

import { LanguageToggle } from '@/components/LanguageToggle';

type TabKey = 'process' | 'history' | 'account';
// ... existing types ...

// ... inside DashboardPage ...
// ... existing navbar code ...
// ... types start here
type TranscribeMode = 'fast' | 'balanced' | 'turbo' | 'best';
type TranscribeProvider = 'local' | 'openai';

const statusStyles: Record<string, string> = {
  completed: 'bg-green-500/15 text-green-300 border-green-500/30',
  processing: 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/40',
  pending: 'bg-[var(--muted)]/10 text-[var(--muted)] border-[var(--border)]',
  failed: 'bg-[var(--danger)]/15 text-[var(--danger)] border-[var(--danger)]/40',
};

function formatDate(ts: string | number): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { t } = useI18n();

  const [activeTab, setActiveTab] = useState<TabKey>('process');
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

  // Processing settings
  const [showSettings, setShowSettings] = useState(false);
  const [transcribeMode, setTranscribeMode] = useState<TranscribeMode>('turbo');
  const [transcribeProvider, setTranscribeProvider] = useState<TranscribeProvider>('local');
  const [outputQuality, setOutputQuality] = useState<'low size' | 'balanced' | 'high quality'>('balanced');
  const [useAI, setUseAI] = useState(false);
  const [contextPrompt, setContextPrompt] = useState('');

  // Account
  const [profileName, setProfileName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [accountMessage, setAccountMessage] = useState('');
  const [accountError, setAccountError] = useState('');
  const [accountSaving, setAccountSaving] = useState(false);

  useEffect(() => {
    if (!isLoading && !user) {
      router.push('/login');
    }
  }, [user, isLoading, router]);

  useEffect(() => {
    if (user) {
      setProfileName(user.name);
    }
  }, [user]);

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
      if (latest && !selectedJob) {
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
    if (activeTab !== 'process') {
      loadHistory();
    }
  }, [user, isLoading, activeTab, loadJobs, loadHistory]);

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

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setError('');
    }
  };

  const handleProcess = async () => {
    if (!selectedFile) return;

    setIsProcessing(true);
    setError('');
    setProgress(0);
    setSelectedJob(null);
    setStatusMessage(t('statusUploading'));

    // Map transcribe mode to model size
    const modelMap: Record<TranscribeMode, string> = {
      fast: 'tiny',
      balanced: 'medium',
      turbo: 'deepdml/faster-whisper-large-v3-turbo-ct2',
      best: 'large-v3',
    };
    const hostedModel = 'openai/gpt-4o-mini-transcribe';
    const provider = transcribeProvider;
    const selectedModel = provider === 'openai' ? hostedModel : modelMap[transcribeMode];

    try {
      const result = await api.processVideo(selectedFile, {
        transcribe_model: selectedModel,
        transcribe_provider: provider,
        openai_model: provider === 'openai' ? hostedModel : undefined,
        video_quality: outputQuality,
        use_llm: useAI,
        context_prompt: contextPrompt,
      });
      setJobId(result.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('startProcessingError'));
      setIsProcessing(false);
    }
  };

  const handleProfileSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;

    setAccountError('');
    setAccountMessage('');
    setAccountSaving(true);

    try {
      if (profileName && profileName !== user.name) {
        await api.updateProfile(profileName);
        await refreshUser();
        setAccountMessage(t('profileUpdated'));
      }

      if (user.provider === 'local' && (password || confirmPassword)) {
        if (password !== confirmPassword) {
          setAccountError(t('passwordsMismatch'));
          setAccountSaving(false);
          return;
        }
        await api.updatePassword(password, confirmPassword);
        setPassword('');
        setConfirmPassword('');
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

  const videoUrl = buildStaticUrl(selectedJob?.result_data?.public_url || selectedJob?.result_data?.video_path);
  const artifactUrl = buildStaticUrl(selectedJob?.result_data?.artifact_url || selectedJob?.result_data?.artifacts_dir);

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
            <div className="flex items-center gap-1 bg-white/5 border border-[var(--border)] rounded-full p-1">
              {(['process', 'history', 'account'] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-2 rounded-full text-sm font-medium transition-colors ${activeTab === tab
                    ? 'bg-white text-[var(--background)] shadow-[0_10px_40px_rgba(255,255,255,0.07)]'
                    : 'text-[var(--muted)] hover:text-[var(--foreground)]'
                    }`}
                >
                  {tab === 'process' && t('tabWorkspace')}
                  {tab === 'history' && t('tabHistory')}
                  {tab === 'account' && t('tabAccount')}
                </button>
              ))}
            </div>
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
            <div className="flex flex-wrap gap-2 text-sm">
              <span className="px-3 py-1 rounded-full bg-[var(--surface-elevated)] border border-[var(--border)]">{t('heroFeaturePhone')}</span>
              <span className="px-3 py-1 rounded-full bg-[var(--surface-elevated)] border border-[var(--border)]">{t('heroFeatureCuts')}</span>
              <span className="px-3 py-1 rounded-full bg-[var(--surface-elevated)] border border-[var(--border)]">{t('heroFeatureExport')}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 w-full max-w-md">
            <div className="card p-4 border-[var(--border)]/80">
              <p className="text-[var(--muted)] text-xs uppercase tracking-wide">{t('pipelineLabel')}</p>
              <p className="text-xl font-semibold">{statusMessage || (isProcessing ? t('statusProcessing') : selectedJob?.status === 'completed' ? t('statusCompleted') : t('statusIdle'))}</p>
              <p className="text-[var(--muted)] text-xs mt-1">{progress}% {t('statusSynced')}</p>
            </div>

            <div className="card p-4 border-[var(--border)]/80">
              <p className="text-[var(--muted)] text-xs uppercase tracking-wide">{t('engineLabel')}</p>
              <p className="text-xl font-semibold">
                {transcribeProvider === 'openai' ? t('engineHostedName') : transcribeMode}
              </p>
              <p className="text-[var(--muted)] text-xs mt-1">
                {transcribeProvider === 'openai' ? t('engineHostedSubtitle') : t('engineLocalSubtitle')}
              </p>
            </div>
            <div className="card p-4 border-[var(--border)]/80">
              <p className="text-[var(--muted)] text-xs uppercase tracking-wide">{t('aiCopyLabel')}</p>
              <p className="text-xl font-semibold">{useAI ? t('statusCompleted') : t('statusIdle')}</p>
              <p className="text-[var(--muted)] text-xs mt-1">{t('aiCopyNote')}</p>
            </div>
          </div>
        </section>

        {activeTab === 'process' && (
          <div className="grid xl:grid-cols-[1.05fr,0.95fr] gap-6">
            <div className="space-y-4">
              <div
                className="card relative overflow-hidden cursor-pointer group transition-all hover:border-[var(--accent)]/60"
                data-clickable="true"
                onClick={() => fileInputRef.current?.click()}
              >
                <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity bg-gradient-to-br from-[var(--accent)]/5 via-transparent to-[var(--accent-secondary)]/10 pointer-events-none" />
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="video/mp4,video/quicktime,video/x-matroska"
                  onChange={handleFileSelect}
                  className="hidden"
                />
                {selectedFile ? (
                  <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between relative">
                    <div className="flex items-start gap-3">
                      <div className="text-4xl">🎥</div>
                      <div>
                        <p className="text-xl font-semibold break-words [overflow-wrap:anywhere]">{selectedFile.name}</p>
                        <p className="text-[var(--muted)] mt-1">
                          {(selectedFile.size / (1024 * 1024)).toFixed(1)} MB · MP4 / MOV / MKV
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
                      <span className="h-2 w-2 rounded-full bg-[var(--accent)] animate-pulse" />
                      {t('uploadReady')}
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-12 relative">
                    <div className="text-6xl mb-3 opacity-80">📤</div>
                    <p className="text-2xl font-semibold mb-1">{t('uploadDropTitle')}</p>
                    <p className="text-[var(--muted)]">{t('uploadDropSubtitle')}</p>
                    <p className="text-xs text-[var(--muted)] mt-4">{t('uploadDropFootnote')}</p>
                  </div>
                )}
              </div>

              <div className="card space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('controlsLabel')}</p>
                    <h3 className="text-xl font-semibold">{t('controlsTitle')}</h3>
                  </div>
                  <button
                    onClick={() => setShowSettings(!showSettings)}
                    className="text-sm text-[var(--muted)] hover:text-[var(--foreground)]"
                  >
                    {showSettings ? t('controlsHideDetails') : t('controlsShowDetails')}
                  </button>
                </div>

                <div className="grid md:grid-cols-2 gap-3">
                  <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-3">
                    <p className="text-xs text-[var(--muted)] uppercase tracking-wide">{t('engineLabel')}</p>
                    <p className="font-semibold">
                      {transcribeProvider === 'openai' ? t('engineHostedName') : t('engineLocalTurbo')}
                    </p>
                    <p className="text-xs text-[var(--muted)] mt-1">
                      {transcribeProvider === 'openai' ? 'gpt-4o-mini-transcribe' : transcribeMode}
                    </p>
                  </div>
                  <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-3">
                    <p className="text-xs text-[var(--muted)] uppercase tracking-wide">{t('qualityLabel')}</p>
                    <p className="font-semibold capitalize">{outputQuality}</p>
                    <p className="text-xs text-[var(--muted)] mt-1">{useAI ? t('aiToggleLabel') : t('aiCopyLabel')}</p>
                  </div>
                </div>

                {showSettings && (
                  <div className="space-y-5 pt-3 border-t border-[var(--border)]">
                    <div>
                      <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                        {t('engineLabel')}
                      </label>
                      <div className="grid grid-cols-2 gap-2">
                        {(['local', 'openai'] as const).map((provider) => (
                          <button
                            key={provider}
                            onClick={() => setTranscribeProvider(provider)}
                            className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${transcribeProvider === provider
                              ? 'bg-[var(--accent)] text-black'
                              : 'bg-[var(--surface-elevated)] text-[var(--muted)] hover:text-[var(--foreground)]'
                              }`}
                          >
                            {provider === 'local' ? t('engineToggleLocal') : t('engineToggleHosted')}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                        {t('speedAccuracyLabel')}
                      </label>
                      {transcribeProvider === 'local' ? (
                        <>
                          <div className="grid grid-cols-4 gap-2">
                            {(['fast', 'balanced', 'turbo', 'best'] as const).map((mode) => (
                              <button
                                key={mode}
                                onClick={() => setTranscribeMode(mode)}
                                className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${transcribeMode === mode
                                  ? 'bg-[var(--accent)] text-black'
                                  : 'bg-[var(--surface-elevated)] text-[var(--muted)] hover:text-[var(--foreground)]'
                                  }`}
                              >
                                {mode.charAt(0).toUpperCase() + mode.slice(1)}
                              </button>
                            ))}
                          </div>
                        </>
                      ) : (
                        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 text-sm text-left">
                          {t('hostedNote')}
                        </div>
                      )}
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                        {t('qualityLabel')}
                      </label>
                      <div className="grid grid-cols-3 gap-2">
                        {(['low size', 'balanced', 'high quality'] as const).map((quality) => (
                          <button
                            key={quality}
                            onClick={() => setOutputQuality(quality)}
                            className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${outputQuality === quality
                              ? 'bg-[var(--accent)] text-black'
                              : 'bg-[var(--surface-elevated)] text-[var(--muted)] hover:text-[var(--foreground)]'
                              }`}
                          >
                            {quality
                              .split(' ')
                              .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                              .join(' ')}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <label className="flex items-center gap-3 cursor-pointer">
                        <div
                          onClick={() => setUseAI(!useAI)}
                          className={`w-11 h-6 rounded-full transition-colors relative ${useAI ? 'bg-[var(--accent)]' : 'bg-[var(--surface-elevated)]'}`}
                        >
                          <div
                            className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform ${useAI ? 'translate-x-6' : 'translate-x-1'}`}
                          />
                        </div>
                        <span className="font-medium">{t('aiToggleLabel')}</span>
                      </label>
                      <p className="text-xs text-[var(--muted)] mt-1 ml-14">{t('aiToggleDescription')}</p>
                    </div>

                    {useAI && (
                      <div>
                        <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                          {t('contextLabel')}
                        </label>
                        <textarea
                          value={contextPrompt}
                          onChange={(e) => setContextPrompt(e.target.value)}
                          placeholder={t('contextPlaceholder')}
                          className="input-field h-20 resize-none"
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>

              {error && (
                <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/30 text-[var(--danger)] px-6 py-4 rounded-xl">
                  {error}
                </div>
              )}

              {selectedFile && !isProcessing && (
                <div className="flex flex-wrap items-center gap-3">
                  <button onClick={handleProcess} className="btn-primary text-lg px-8 py-4">
                    ✨ {t('processingStart')}
                  </button>
                  <button
                    onClick={resetProcessing}
                    className="btn-secondary text-sm"
                  >
                    {t('processingReset')}
                  </button>
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div className="card space-y-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('liveOutputLabel')}</p>
                    <h3 className="text-2xl font-semibold break-words [overflow-wrap:anywhere]">
                      {selectedJob?.result_data?.original_filename || t('liveOutputPlaceholderTitle')}
                    </h3>
                    <p className="text-sm text-[var(--muted)]">{t('liveOutputSubtitle')}</p>
                  </div>
                  <span className={`px-3 py-1 rounded-full text-xs font-semibold border ${statusStyles[selectedJob?.status || (isProcessing ? 'processing' : 'pending')] || ''}`}>
                    {selectedJob?.status ? selectedJob.status.toUpperCase() : isProcessing ? t('liveOutputStatusProcessing') : t('liveOutputStatusIdle')}
                  </span>
                </div>

                {isProcessing && (
                  <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{statusMessage || t('progressLabel')}</span>
                      <span className="text-[var(--accent)] font-semibold">{progress}%</span>
                    </div>
                    <div className="w-full bg-[var(--surface)] rounded-full h-2 overflow-hidden">
                      <div
                        className="bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] h-2 rounded-full transition-all duration-300"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </div>
                )}

                {selectedJob && selectedJob.status === 'completed' ? (
                  <div className="grid lg:grid-cols-[420px,1fr] gap-6 items-start">
                    <div className="w-full max-w-[440px] mx-auto">
                      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] overflow-hidden shadow-2xl">
                        {videoUrl ? (
                          <video
                            className="w-full aspect-[9/16] object-contain bg-black"
                            src={videoUrl}
                            controls
                          />
                        ) : (
                          <div className="aspect-[9/16] flex items-center justify-center text-[var(--muted)] text-sm">
                            {t('videoReadyPlaceholder')}
                          </div>
                        )}
                      </div>
                      <p className="text-xs text-[var(--muted)] mt-2 text-center">{t('playerNote')}</p>
                    </div>
                    <div className="space-y-3">
                      <p className="text-sm text-[var(--muted)]">{t('renderFinishedDescription')}</p>
                      <div className="flex flex-wrap gap-3">
                        {videoUrl && (
                          <>
                            <a
                              className="btn-primary"
                              href={videoUrl}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {t('viewVideo')}
                            </a>
                            <a
                              className="btn-secondary"
                              href={videoUrl}
                              download={selectedJob.result_data?.original_filename || 'processed.mp4'}
                            >
                              {t('downloadMp4')}
                            </a>
                          </>
                        )}
                        {artifactUrl && (
                          <a
                            className="btn-secondary"
                            href={artifactUrl}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {t('artifactsFolder')}
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-6 text-[var(--muted)] text-sm text-center">
                    {t('renderPlaceholder')}
                  </div>
                )}
              </div>

              <div className="card">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('logbookLabel')}</p>
                    <h3 className="text-lg font-semibold">{t('recentJobsTitle')}</h3>
                  </div>
                  {jobsLoading && <span className="text-xs text-[var(--muted)]">{t('refreshingLabel')}</span>}
                </div>
                {recentJobs.length === 0 && (
                  <p className="text-[var(--muted)] text-sm">{t('noRunsYet')}</p>
                )}
                <div className="space-y-3">
                  {recentJobs.map((job) => {
                    const publicUrl = buildStaticUrl(job.result_data?.public_url || job.result_data?.video_path);
                    return (
                      <div
                        key={job.id}
                        data-testid={`recent-job-${job.id}`}
                        className="flex flex-wrap sm:flex-nowrap items-start sm:items-center justify-between gap-3 p-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="font-semibold break-words [overflow-wrap:anywhere]">
                            {job.result_data?.original_filename || `${t('recentJobsTitle')} ${job.id.slice(0, 6)}`}
                          </div>
                          <div className="text-xs text-[var(--muted)] mt-1 leading-snug break-words [overflow-wrap:anywhere]">
                            {formatDate((job.updated_at || job.created_at) * 1000)}
                            {' · '}
                            {(job.result_data?.transcribe_provider || 'local') === 'openai' ? t('engineHostedName') : (job.result_data?.model_size || 'model')}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap sm:justify-end flex-shrink-0">
                          <span className={`px-3 py-1 rounded-full text-xs font-semibold border ${statusStyles[job.status] || ''}`}>
                            {job.status}
                          </span>
                          {job.status === 'completed' && publicUrl && (
                            <button
                              onClick={() => setSelectedJob(job)}
                              className="btn-secondary text-xs"
                            >
                              {t('jobView')}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'history' && (
          <div className="flex flex-col gap-6">
            <div className="card">
              <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('timelineLabel')}</p>
                  <h2 className="text-2xl font-bold">{t('activityTitle')}</h2>
                  <p className="text-[var(--muted)] text-sm">{t('activitySubtitle')}</p>
                </div>
                <button
                  className="btn-secondary text-sm"
                  onClick={loadHistory}
                  disabled={historyLoading}
                >
                  {t('refresh')}
                </button>
              </div>
              {historyLoading && <p className="text-[var(--muted)]">{t('loadingHistory')}</p>}
              {historyError && (
                <p className="text-[var(--danger)] text-sm">{historyError}</p>
              )}
              {!historyLoading && historyItems.length === 0 && (
                <p className="text-[var(--muted)]">{t('noHistory')}</p>
              )}
              <div className="space-y-3">
                {historyItems.map((evt) => (
                  <div
                    key={`${evt.ts}-${evt.kind}`}
                    className="p-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]"
                  >
                    <div className="flex flex-wrap items-start sm:items-center justify-between gap-2">
                      <div className="font-semibold break-words [overflow-wrap:anywhere]">{evt.summary}</div>
                      <span className="text-xs text-[var(--muted)] sm:text-right">{formatDate(evt.ts)}</span>
                    </div>
                    <div className="text-xs text-[var(--muted)] mt-1 uppercase tracking-wide">
                      {evt.kind.replace(/_/g, ' ')}
                    </div>
                  </div>
                ))}
              </div>
            </div>


          </div>
        )}

        {activeTab === 'account' && (
          <div className="flex flex-col gap-6 max-w-2xl mx-auto">
            <div className="card space-y-4">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('profileLabel')}</p>
                <h2 className="text-2xl font-bold">{t('accountSettingsTitle')}</h2>
                <p className="text-sm text-[var(--muted)]">{t('accountSettingsSubtitle')}</p>
              </div>
              <form className="space-y-4" onSubmit={handleProfileSave}>
                <div>
                  <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                    {t('displayNameLabel')}
                  </label>
                  <input
                    className="input-field"
                    value={profileName}
                    onChange={(e) => setProfileName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                    {t('emailLabel')}
                  </label>
                  <input className="input-field" value={user.email} disabled />
                </div>
                {user.provider === 'local' && (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                        {t('newPasswordLabel')}
                      </label>
                      <input
                        type="password"
                        className="input-field"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="••••••••"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                        {t('confirmPasswordLabel')}
                      </label>
                      <input
                        type="password"
                        className="input-field"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        placeholder="••••••••"
                      />
                    </div>
                  </>
                )}
                {accountError && (
                  <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/30 text-[var(--danger)] px-4 py-3 rounded-lg text-sm">
                    {accountError}
                  </div>
                )}
                {accountMessage && (
                  <div className="bg-[var(--accent-secondary)]/10 border border-[var(--accent-secondary)]/30 text-[var(--accent-secondary)] px-4 py-3 rounded-lg text-sm">
                    {accountMessage}
                  </div>
                )}
                <button type="submit" className="btn-primary" disabled={accountSaving}>
                  {t('saveChanges')}
                </button>
              </form>
            </div>

            <div className="card">
              <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('sessionLabel')}</p>
              <h3 className="text-lg font-semibold mb-2">{t('currentSessionTitle')}</h3>
              <p className="text-[var(--muted)] text-sm">{t('currentSessionDescription').replace('{provider}', user.provider)}</p>
              <p className="text-[var(--muted)] text-sm mt-3">{t('signOutReminder')}</p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
