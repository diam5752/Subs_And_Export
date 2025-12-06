'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { api, API_BASE, JobResponse, HistoryEvent } from '@/lib/api';

type TabKey = 'process' | 'history' | 'account';

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
  const [transcribeMode, setTranscribeMode] = useState<'fast' | 'balanced' | 'turbo' | 'best'>('turbo');
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
      setRecentJobs(jobs);
      const latest = jobs.find((job) => job.status === 'completed' && job.result_data);
      if (latest && !selectedJob) {
        setSelectedJob(latest);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load recent jobs');
    } finally {
      setJobsLoading(false);
    }
  }, [user, selectedJob]);

  const loadHistory = useCallback(async () => {
    if (!user) return;
    setHistoryLoading(true);
    setHistoryError('');
    try {
      const data = await api.getHistory(50);
      setHistoryItems(data);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Unable to load history');
    } finally {
      setHistoryLoading(false);
    }
  }, [user]);

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
        setStatusMessage(job.message || (job.status === 'processing' ? 'Processing...' : ''));

        if (job.status === 'completed') {
          setIsProcessing(false);
          setJobId(null);
          setSelectedJob(job);
          setError('');
          clearInterval(pollInterval);
          refreshActivity();
        } else if (job.status === 'failed') {
          setError(job.message || 'Processing failed');
          setIsProcessing(false);
          setJobId(null);
          clearInterval(pollInterval);
          refreshActivity();
        }
      } catch {
        clearInterval(pollInterval);
        setIsProcessing(false);
        setError('Failed to check job status');
      }
    }, 1000);

    return () => clearInterval(pollInterval);
  }, [jobId, refreshActivity]);

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
    setStatusMessage('Uploading...');

    // Map transcribe mode to model size
    const modelMap: Record<string, string> = {
      fast: 'tiny',
      balanced: 'medium',
      turbo: 'deepdml/faster-whisper-large-v3-turbo-ct2',
      best: 'large-v3',
    };

    try {
      const result = await api.processVideo(selectedFile, {
        transcribe_model: modelMap[transcribeMode],
        video_quality: outputQuality,
        use_llm: useAI,
        context_prompt: contextPrompt,
      });
      setJobId(result.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start processing');
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
        setAccountMessage('Profile updated');
      }

      if (user.provider === 'local' && (password || confirmPassword)) {
        if (password !== confirmPassword) {
          setAccountError('Passwords do not match');
          setAccountSaving(false);
          return;
        }
        await api.updatePassword(password, confirmPassword);
        setPassword('');
        setConfirmPassword('');
        setAccountMessage('Password updated');
      }
    } catch (err) {
      setAccountError(err instanceof Error ? err.message : 'Unable to update account');
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
        <div className="text-[var(--muted)]">Loading...</div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="min-h-screen relative overflow-hidden">
      <div className="pointer-events-none absolute -left-10 -top-10 h-64 w-64 rounded-full bg-[var(--accent)]/10 blur-3xl" />
      <div className="pointer-events-none absolute right-0 top-20 h-56 w-56 rounded-full bg-[var(--accent-secondary)]/10 blur-3xl" />

      <nav className="sticky top-0 z-20 backdrop-blur-xl bg-[var(--background)]/70 border-b border-[var(--border)]/60 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-11 w-11 rounded-2xl bg-white/5 border border-[var(--border)] flex items-center justify-center text-xl">🎥</div>
            <div>
              <p className="text-[var(--muted)] text-xs uppercase tracking-[0.2em]">Greek Sub Publisher</p>
              <p className="text-xl font-semibold">Futurist Studio</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {(['process', 'history', 'account'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 rounded-full text-sm font-medium transition-colors border ${activeTab === tab
                    ? 'bg-white text-[var(--background)] border-white'
                    : 'border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--accent)]/40'
                  }`}
              >
                {tab === 'process' && 'Workspace'}
                {tab === 'history' && 'History'}
                {tab === 'account' && 'Account'}
              </button>
            ))}
            <div className="h-6 w-px bg-[var(--border)]" />
            <div className="flex items-center gap-3 text-sm">
              <div className="px-3 py-2 rounded-lg bg-white/5 border border-[var(--border)]">
                <div className="font-semibold">{user.name}</div>
                <div className="text-[var(--muted)] text-xs">{user.provider} session</div>
              </div>
              <button onClick={logout} className="btn-secondary text-sm py-2 px-4">
                Sign Out
              </button>
            </div>
          </div>
        </div>
      </nav>

      <main className="relative max-w-6xl mx-auto px-6 py-10 space-y-10">
        <section className="card border-[var(--border)]/70 bg-white/5 flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-3 max-w-2xl">
            <p className="text-[var(--muted)] text-sm uppercase tracking-[0.25em]">Minimal, Apple-inspired flow</p>
            <h1 className="text-4xl lg:text-5xl font-semibold leading-tight">
              Slick subtitle lab inspired by the best of CapCut
            </h1>
            <p className="text-[var(--muted)] text-lg">
              Drop your vertical clips, let the AI align Greek subtitles, and ship export-ready reels in a few clicks.
            </p>
            <div className="flex flex-wrap gap-3">
              <span className="px-3 py-2 rounded-full bg-white/5 border border-[var(--border)] text-sm">Live sync + auto styling</span>
              <span className="px-3 py-2 rounded-full bg-white/5 border border-[var(--border)] text-sm">TikTok-ready exports</span>
              <span className="px-3 py-2 rounded-full bg-white/5 border border-[var(--border)] text-sm">LLM-powered hooks</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 w-full max-w-md">
            <div className="card p-4 border-[var(--border)]/80">
              <p className="text-[var(--muted)] text-xs">Latest status</p>
              <p className="text-xl font-semibold">{statusMessage || (selectedJob?.status === 'completed' ? 'Completed' : 'Idle')}</p>
              <p className="text-[var(--muted)] text-xs mt-1">{progress}% synced</p>
            </div>
            <div className="card p-4 border-[var(--border)]/80">
              <p className="text-[var(--muted)] text-xs">Recent renders</p>
              <p className="text-xl font-semibold">{recentJobs.length || 0}</p>
              <p className="text-[var(--muted)] text-xs mt-1">kept for quick reuse</p>
            </div>
            <div className="card p-4 border-[var(--border)]/80">
              <p className="text-[var(--muted)] text-xs">Mode</p>
              <p className="text-xl font-semibold">{transcribeMode}</p>
              <p className="text-[var(--muted)] text-xs mt-1">speed / accuracy preset</p>
            </div>
            <div className="card p-4 border-[var(--border)]/80">
              <p className="text-[var(--muted)] text-xs">AI copy</p>
              <p className="text-xl font-semibold">{useAI ? 'Enabled' : 'Manual'}</p>
              <p className="text-[var(--muted)] text-xs mt-1">hooks + captions</p>
            </div>
          </div>
        </section>

        {activeTab === 'process' && (
          <>

            <div className="grid lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 space-y-6">
                <div
                  className="card text-center cursor-pointer hover:border-[var(--accent)] transition-colors"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="video/mp4,video/quicktime,video/x-matroska"
                    onChange={handleFileSelect}
                    className="hidden"
                  />

                  {selectedFile ? (
                    <div className="py-8">
                      <div className="text-6xl mb-4">🎥</div>
                      <p className="text-xl font-medium">{selectedFile.name}</p>
                      <p className="text-[var(--muted)] mt-2">
                        {(selectedFile.size / (1024 * 1024)).toFixed(1)} MB
                      </p>
                    </div>
                  ) : (
                    <div className="py-12">
                      <div className="text-6xl mb-4 opacity-50">📤</div>
                      <p className="text-xl font-medium mb-2">Drop your video here</p>
                      <p className="text-[var(--muted)]">or click to browse</p>
                      <p className="text-sm text-[var(--muted)] mt-4">Supports MP4, MOV, MKV</p>
                    </div>
                  )}
                </div>

                {selectedFile && !isProcessing && (
                  <div className="card space-y-4">
                    <div className="flex items-center justify-between">
                      <div className="font-semibold flex items-center gap-2">
                        <span>⚙️</span> Processing Settings
                      </div>
                      <button
                        onClick={() => setShowSettings(!showSettings)}
                        className="text-sm text-[var(--muted)] hover:text-[var(--foreground)]"
                      >
                        {showSettings ? 'Hide' : 'Show'}
                      </button>
                    </div>

                    {showSettings && (
                      <div className="space-y-5 pt-2 border-t border-[var(--border)]">
                        <div>
                          <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                            Speed / Accuracy
                          </label>
                          <div className="grid grid-cols-4 gap-2">
                            {(['fast', 'balanced', 'turbo', 'best'] as const).map((mode) => (
                              <button
                                key={mode}
                                onClick={() => setTranscribeMode(mode)}
                                className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${transcribeMode === mode
                                    ? 'bg-[var(--accent)] text-white'
                                    : 'bg-[var(--surface-elevated)] text-[var(--muted)] hover:text-[var(--foreground)]'
                                  }`}
                              >
                                {mode.charAt(0).toUpperCase() + mode.slice(1)}
                              </button>
                            ))}
                          </div>
                          <p className="text-xs text-[var(--muted)] mt-1">
                            Turbo provides the best balance of speed and accuracy
                          </p>
                        </div>

                        <div>
                          <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                            Output Quality
                          </label>
                          <div className="grid grid-cols-3 gap-2">
                            {(['low size', 'balanced', 'high quality'] as const).map((quality) => (
                              <button
                                key={quality}
                                onClick={() => setOutputQuality(quality)}
                                className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${outputQuality === quality
                                    ? 'bg-[var(--accent)] text-white'
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
                            <span className="font-medium">AI Viral Intelligence</span>
                          </label>
                          <p className="text-xs text-[var(--muted)] mt-1 ml-14">
                            Generate viral titles and descriptions using GPT-4
                          </p>
                        </div>

                        {useAI && (
                          <div>
                            <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                              Context Hints
                            </label>
                            <textarea
                              value={contextPrompt}
                              onChange={(e) => setContextPrompt(e.target.value)}
                              placeholder="Names, specific terms, topics..."
                              className="input-field h-20 resize-none"
                            />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {isProcessing && (
                  <div className="card">
                    <div className="flex items-center justify-between mb-3">
                      <span className="font-medium">{statusMessage || 'Processing...'}</span>
                      <span className="text-[var(--accent)]">{progress}%</span>
                    </div>
                    <div className="w-full bg-[var(--surface-elevated)] rounded-full h-2">
                      <div
                        className="bg-[var(--accent)] h-2 rounded-full transition-all duration-300"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </div>
                )}

                {error && (
                  <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/30 text-[var(--danger)] px-6 py-4 rounded-xl">
                    {error}
                  </div>
                )}

                {selectedFile && !isProcessing && (
                  <div className="text-left">
                    <button onClick={handleProcess} className="btn-primary text-lg px-8 py-4">
                      ✨ Start Magic Processing
                    </button>
                    <button
                      onClick={resetProcessing}
                      className="btn-secondary ml-3 text-sm"
                    >
                      Reset
                    </button>
                  </div>
                )}

                {selectedJob && selectedJob.status === 'completed' && (
                  <div className="card bg-[var(--accent-secondary)]/10 border-[var(--accent-secondary)]/30">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <p className="text-sm text-[var(--muted)]">Latest render</p>
                        <h3 className="text-2xl font-bold">
                          {selectedJob.result_data?.original_filename || 'Processed video'}
                        </h3>
                      </div>
                      <span className={`px-3 py-1 rounded-full text-xs font-semibold border ${statusStyles[selectedJob.status] || ''}`}>
                        {selectedJob.status.toUpperCase()}
                      </span>
                    </div>
                    {videoUrl ? (
                      <video
                        className="w-full rounded-lg border border-[var(--border)]"
                        src={videoUrl}
                        controls
                      />
                    ) : (
                      <p className="text-[var(--muted)]">Video ready — download below.</p>
                    )}
                    <div className="flex flex-wrap gap-3 mt-4">
                      {videoUrl && (
                        <>
                          <a
                            className="btn-primary"
                            href={videoUrl}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View video
                          </a>
                          <a
                            className="btn-secondary"
                            href={videoUrl}
                            download={selectedJob.result_data?.original_filename || 'processed.mp4'}
                          >
                            Download MP4
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
                          Artifacts folder
                        </a>
                      )}
                    </div>
                  </div>
                )}
              </div>

              <div className="space-y-4">
                <div className="card">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-lg font-semibold">Recent jobs</h3>
                    {jobsLoading && <span className="text-xs text-[var(--muted)]">Refreshing…</span>}
                  </div>
                  {recentJobs.length === 0 && (
                    <p className="text-[var(--muted)] text-sm">No runs yet — upload a video to get started.</p>
                  )}
                  <div className="space-y-3">
                    {recentJobs.map((job) => {
                      const publicUrl = buildStaticUrl(job.result_data?.public_url || job.result_data?.video_path);
                      return (
                        <div
                          key={job.id}
                          className="flex items-center justify-between p-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]"
                        >
                          <div>
                            <div className="font-semibold">
                              {job.result_data?.original_filename || `Job ${job.id.slice(0, 6)}`}
                            </div>
                            <div className="text-xs text-[var(--muted)]">
                              {formatDate((job.updated_at || job.created_at) * 1000)}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className={`px-3 py-1 rounded-full text-xs font-semibold border ${statusStyles[job.status] || ''}`}>
                              {job.status}
                            </span>
                            {job.status === 'completed' && publicUrl && (
                              <button
                                onClick={() => setSelectedJob(job)}
                                className="btn-secondary text-xs"
                              >
                                View
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
          </>
        )}

        {activeTab === 'history' && (
          <div className="grid lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 card">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-2xl font-bold">Activity</h2>
                  <p className="text-[var(--muted)]">Processing, uploads, and OAuth events.</p>
                </div>
                <button
                  className="btn-secondary text-sm"
                  onClick={loadHistory}
                  disabled={historyLoading}
                >
                  Refresh
                </button>
              </div>
              {historyLoading && <p className="text-[var(--muted)]">Loading history...</p>}
              {historyError && (
                <p className="text-[var(--danger)] text-sm">{historyError}</p>
              )}
              {!historyLoading && historyItems.length === 0 && (
                <p className="text-[var(--muted)]">No history yet.</p>
              )}
              <div className="space-y-3">
                {historyItems.map((evt) => (
                  <div
                    key={`${evt.ts}-${evt.kind}`}
                    className="p-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]"
                  >
                    <div className="flex items-center justify-between">
                      <div className="font-semibold">{evt.summary}</div>
                      <span className="text-xs text-[var(--muted)]">{formatDate(evt.ts)}</span>
                    </div>
                    <div className="text-xs text-[var(--muted)] mt-1 uppercase tracking-wide">
                      {evt.kind.replace(/_/g, ' ')}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold">Job Summary</h3>
                {jobsLoading && <span className="text-xs text-[var(--muted)]">Refreshing…</span>}
              </div>
              {recentJobs.length === 0 && (
                <p className="text-[var(--muted)] text-sm">No jobs logged.</p>
              )}
              <div className="space-y-2">
                {recentJobs.map((job) => (
                  <div key={job.id} className="flex items-center justify-between p-3 rounded-lg bg-[var(--surface-elevated)] border border-[var(--border)]">
                    <div>
                      <div className="font-semibold text-sm">
                        {job.result_data?.original_filename || job.id.slice(0, 6)}
                      </div>
                      <div className="text-xs text-[var(--muted)]">
                        {job.result_data?.model_size || 'model'} · {job.result_data?.video_crf ? `CRF ${job.result_data.video_crf}` : ''}
                      </div>
                    </div>
                    <span className={`px-3 py-1 rounded-full text-xs font-semibold border ${statusStyles[job.status] || ''}`}>
                      {job.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'account' && (
          <div className="grid lg:grid-cols-2 gap-6">
            <div className="card space-y-4">
              <div>
                <p className="text-sm text-[var(--muted)]">Profile</p>
                <h2 className="text-2xl font-bold">Account settings</h2>
              </div>
              <form className="space-y-4" onSubmit={handleProfileSave}>
                <div>
                  <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                    Display name
                  </label>
                  <input
                    className="input-field"
                    value={profileName}
                    onChange={(e) => setProfileName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                    Email
                  </label>
                  <input className="input-field" value={user.email} disabled />
                </div>
                {user.provider === 'local' && (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                        New password
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
                        Confirm password
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
                  Save changes
                </button>
              </form>
            </div>

            <div className="space-y-4">
              <div className="card">
                <h3 className="text-lg font-semibold mb-2">Session</h3>
                <p className="text-[var(--muted)] text-sm">You are signed in via {user.provider}.</p>
                <div className="flex gap-3 mt-3">
                  <button className="btn-secondary" onClick={refreshUser}>
                    Refresh session
                  </button>
                  <button className="btn-secondary" onClick={logout}>
                    Sign out everywhere
                  </button>
                </div>
              </div>
              <div className="card">
                <h3 className="text-lg font-semibold mb-2">Recent history</h3>
                {historyItems.slice(0, 5).map((evt) => (
                  <div key={`${evt.ts}-${evt.kind}`} className="flex items-center justify-between py-2 border-b border-[var(--border)] last:border-0">
                    <div>
                      <div className="font-semibold text-sm">{evt.summary}</div>
                      <div className="text-xs text-[var(--muted)]">{formatDate(evt.ts)}</div>
                    </div>
                    <span className="text-[var(--muted)] text-xs uppercase">{evt.kind.replace(/_/g, ' ')}</span>
                  </div>
                ))}
                {historyItems.length === 0 && (
                  <p className="text-[var(--muted)] text-sm">No events yet.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
