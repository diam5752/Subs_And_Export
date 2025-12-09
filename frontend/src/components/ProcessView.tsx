import React, { useState, useRef } from 'react';
import { api, JobResponse } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';
import { VideoModal } from './VideoModal';

type TranscribeMode = 'fast' | 'balanced' | 'turbo' | 'best';
type TranscribeProvider = 'local' | 'openai';

interface ProcessViewProps {
    selectedFile: File | null;
    onFileSelect: (file: File | null) => void;
    isProcessing: boolean;
    progress: number;
    statusMessage: string;
    error: string;
    onStartProcessing: (options: ProcessingOptions) => Promise<void>;
    onReset: () => void;
    selectedJob: JobResponse | null;
    onJobSelect: (job: JobResponse | null) => void;
    recentJobs: JobResponse[];
    jobsLoading: boolean;
    statusStyles: Record<string, string>;
    formatDate: (ts: string | number) => string;
    buildStaticUrl: (path?: string | null) => string | null;
    onRefreshJobs: () => Promise<void>;
}

export interface ProcessingOptions {
    transcribeMode: TranscribeMode;
    transcribeProvider: TranscribeProvider;
    outputQuality: 'low size' | 'balanced' | 'high quality';
    useAI: boolean;
    contextPrompt: string;
}

export function ProcessView({
    selectedFile,
    onFileSelect,
    isProcessing,
    progress,
    statusMessage,
    error,
    onStartProcessing,
    onReset,
    selectedJob,
    onJobSelect,
    recentJobs,
    jobsLoading,
    statusStyles,
    formatDate,
    buildStaticUrl,
    onRefreshJobs,
}: ProcessViewProps) {
    const { t } = useI18n();
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Local state for options
    const [showPreview, setShowPreview] = useState(false);
    const [showSettings, setShowSettings] = useState(true);
    const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
    const [transcribeMode, setTranscribeMode] = useState<TranscribeMode>('turbo');
    const [transcribeProvider, setTranscribeProvider] = useState<TranscribeProvider>('local');
    const [outputQuality, setOutputQuality] = useState<'low size' | 'balanced' | 'high quality'>('balanced');
    const [useAI, setUseAI] = useState(false);
    const [contextPrompt, setContextPrompt] = useState('');

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0] || null;
        onFileSelect(file);
    };

    const handleStart = () => {
        onStartProcessing({
            transcribeMode,
            transcribeProvider,
            outputQuality,
            useAI,
            contextPrompt,
        });
    };

    const videoUrl = buildStaticUrl(selectedJob?.result_data?.public_url || selectedJob?.result_data?.video_path);
    const artifactUrl = buildStaticUrl(selectedJob?.result_data?.artifact_url || selectedJob?.result_data?.artifacts_dir);

    return (
        <div className="grid xl:grid-cols-[1.05fr,0.95fr] gap-6">
            <div className="space-y-4">
                {/* Upload Card */}
                <div
                    className="card relative overflow-hidden cursor-pointer group transition-all hover:border-[var(--accent)]/60"
                    data-clickable="true"
                    onClick={() => !isProcessing && fileInputRef.current?.click()}
                >
                    <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity bg-gradient-to-br from-[var(--accent)]/5 via-transparent to-[var(--accent-secondary)]/10 pointer-events-none" />
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/mp4,video/quicktime,video/x-matroska"
                        onChange={handleFileChange}
                        className="hidden"
                        disabled={isProcessing}
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

                {/* Controls Card - Only show when file is selected */}
                {selectedFile && !isProcessing && (
                    <div className="card space-y-4 animate-fade-in">
                        <div
                            className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] pb-3 cursor-pointer group"
                            onClick={() => setShowSettings(!showSettings)}
                        >
                            <div className="flex items-center gap-3">
                                <div>
                                    <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('controlsLabel')}</p>
                                    <h3 className="text-xl font-semibold">{t('controlsTitle')}</h3>
                                </div>
                            </div>
                            <div className={`transition-transform duration-200 ${showSettings ? 'rotate-180' : ''}`}>
                                <svg className="w-5 h-5 text-[var(--muted)] group-hover:text-[var(--foreground)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                </svg>
                            </div>
                        </div>

                        {showSettings && (
                            <div className="space-y-5 pt-1 animate-fade-in">
                                <div>
                                    <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                                        {t('engineLabel')}
                                    </label>
                                    <div className="grid grid-cols-2 gap-3">
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setTranscribeProvider('local');
                                                setTranscribeMode('turbo');
                                            }}
                                            className={`p-3 rounded-lg border text-left transition-all ${transcribeProvider === 'local'
                                                ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                                                : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                }`}
                                        >
                                            <div className="font-semibold">{t('engineLocalTurbo')}</div>
                                            <div className="text-xs text-[var(--muted)]">{t('engineLocalDesc')}</div>
                                        </button>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setTranscribeProvider('openai');
                                            }}
                                            className={`p-3 rounded-lg border text-left transition-all ${transcribeProvider === 'openai'
                                                ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                                                : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                }`}
                                        >
                                            <div className="font-semibold">{t('engineHostedName')}</div>
                                            <div className="text-xs text-[var(--muted)]">{t('engineHostedDesc')}</div>
                                        </button>
                                    </div>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                                        {t('qualityLabel')}
                                    </label>
                                    <div className="grid grid-cols-3 gap-3">
                                        {(['low size', 'balanced', 'high quality'] as const).map((q) => (
                                            <button
                                                key={q}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setOutputQuality(q);
                                                }}
                                                className={`p-2 rounded-lg border text-center text-sm capitalize transition-all ${outputQuality === q
                                                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)] font-medium'
                                                    : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                    }`}
                                            >
                                                {q}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div className="pt-2">
                                    <label className="flex items-center gap-3 cursor-pointer group" onClick={(e) => e.stopPropagation()}>
                                        <div
                                            onClick={() => setUseAI(!useAI)}
                                            className={`w-12 h-6 rounded-full transition-colors relative ${useAI ? 'bg-[var(--accent)]' : 'bg-[var(--border)]'}`}
                                        >
                                            <div className={`absolute top-1 left-1 bg-white w-4 h-4 rounded-full transition-transform ${useAI ? 'translate-x-6' : ''}`} />
                                        </div>
                                        <span className="font-medium">{t('aiToggleLabel')}</span>
                                    </label>
                                    <p className="text-xs text-[var(--muted)] mt-1 ml-14">{t('aiToggleDescription')}</p>
                                </div>

                                {useAI && (
                                    <div className="animate-fade-in" onClick={(e) => e.stopPropagation()}>
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

                        {showSettings && (
                            <div className="flex justify-end gap-3 pt-2">
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        if (fileInputRef.current) {
                                            fileInputRef.current.value = '';
                                        }
                                        onReset();
                                    }}
                                    className="btn-secondary"
                                >
                                    {t('processingReset')}
                                </button>
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setShowSettings(false);
                                        handleStart();
                                    }}
                                    disabled={isProcessing}
                                    className="btn-primary w-full sm:w-auto px-8"
                                >
                                    {t('controlsStart')}
                                </button>
                            </div>
                        )}
                    </div>
                )}

                {error && (
                    <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/30 text-[var(--danger)] px-6 py-4 rounded-xl animate-fade-in">
                        {error}
                    </div>
                )}


            </div>

            <div className="space-y-4">
                {(isProcessing || (selectedJob && selectedJob.status !== 'pending')) && (
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
                            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 space-y-2 animate-fade-in">
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
                            <div className="animate-fade-in relative">
                                {/* Animated shimmer border */}
                                <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-r from-[var(--accent)] via-[var(--accent-secondary)] to-[var(--accent)] bg-[length:200%_100%] animate-shimmer opacity-80" />

                                {/* Inner glow */}
                                <div className="absolute inset-0 rounded-2xl" style={{ boxShadow: '0 0 60px -15px var(--accent), 0 0 30px -10px var(--accent-secondary)' }} />

                                <div className="relative rounded-2xl border border-white/10 bg-[var(--surface-elevated)] overflow-hidden">
                                    {/* Success badge */}
                                    <div className="absolute top-0 right-0 p-4 z-10">
                                        <div className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full bg-gradient-to-r from-emerald-500/20 to-[var(--accent)]/20 backdrop-blur-md text-emerald-300 border border-emerald-500/30">
                                            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                                            Subtitles Ready
                                        </div>
                                    </div>

                                    <div className="flex flex-col sm:flex-row">
                                        {/* Preview Thumbnail Area */}
                                        <div
                                            onClick={() => videoUrl && setShowPreview(true)}
                                            className="relative group cursor-pointer w-full sm:w-1/3 aspect-video sm:aspect-auto sm:h-auto min-h-[180px] bg-black/40 flex items-center justify-center overflow-hidden"
                                        >
                                            {/* Real Video Preview as Thumbnail */}
                                            {videoUrl ? (
                                                <video
                                                    src={`${videoUrl}#t=0.5`}
                                                    className="absolute inset-0 w-full h-full object-cover opacity-70 group-hover:opacity-90 transition-opacity duration-300"
                                                    muted
                                                    playsInline
                                                    preload="metadata"
                                                />
                                            ) : (
                                                <div className="absolute inset-0 bg-gradient-to-br from-[var(--accent)]/20 to-[var(--accent-secondary)]/20 opacity-50" />
                                            )}

                                            {/* Play Button with glow */}
                                            <div className="relative z-10 w-16 h-16 rounded-full bg-white/15 backdrop-blur-sm border border-white/25 flex items-center justify-center group-hover:scale-110 group-hover:bg-white/25 transition-all duration-300" style={{ boxShadow: '0 0 25px rgba(255,255,255,0.2)' }}>
                                                <div className="w-0 h-0 border-t-[10px] border-t-transparent border-l-[18px] border-l-white border-b-[10px] border-b-transparent ml-1" />
                                            </div>

                                            <div className="absolute bottom-3 left-3 text-xs font-medium text-white/90 z-10 drop-shadow-lg">
                                                Click to Preview
                                            </div>
                                        </div>

                                        {/* Details Area */}
                                        <div className="p-6 flex-1 flex flex-col justify-center">
                                            <h4 className="text-xl font-semibold mb-2 line-clamp-2 bg-gradient-to-r from-white to-white/80 bg-clip-text">
                                                {selectedJob.result_data?.original_filename || "Processed Video.mp4"}
                                            </h4>
                                            <div className="flex gap-4 text-sm text-[var(--muted)] mb-6">
                                                <span className="flex items-center gap-1.5">
                                                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
                                                    MP4
                                                </span>
                                                <span>•</span>
                                                <span>{((selectedJob.result_data?.output_size || selectedFile?.size || 0) / (1024 * 1024)).toFixed(1)} MB</span>
                                            </div>

                                            <div className="flex flex-wrap gap-3">
                                                {videoUrl && (
                                                    <a
                                                        className="btn-primary items-center gap-2 inline-flex"
                                                        href={videoUrl}
                                                        download={selectedJob.result_data?.original_filename || 'processed.mp4'}
                                                    >
                                                        ⬇️ Download MP4
                                                    </a>
                                                )}
                                                <button
                                                    onClick={() => videoUrl && setShowPreview(true)}
                                                    className="btn-secondary"
                                                >
                                                    ▶️ Preview
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ) : null}
                    </div>
                )}

                {/* Recent Jobs with Expiry */}
                <div className="card mt-6 border-none bg-transparent shadow-none p-0">
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                        <div>
                            <h3 className="text-lg font-semibold">History</h3>
                            <p className="text-xs text-[var(--muted)]">Items expire in 24 hours</p>
                        </div>
                        {jobsLoading && <span className="text-xs text-[var(--muted)]">{t('refreshingLabel')}</span>}
                    </div>
                    {recentJobs.length === 0 && (
                        <p className="text-[var(--muted)] text-sm">{t('noRunsYet')}</p>
                    )}
                    <div className="space-y-2">
                        {recentJobs.map((job) => {
                            const publicUrl = buildStaticUrl(job.result_data?.public_url || job.result_data?.video_path);
                            const timestamp = (job.updated_at || job.created_at) * 1000;
                            const isExpired = (Date.now() - timestamp) > 24 * 60 * 60 * 1000;

                            return (
                                <div
                                    key={job.id}
                                    className={`flex flex-wrap sm:flex-nowrap items-center justify-between gap-3 p-3 rounded-lg border ${isExpired ? 'border-[var(--border)]/30 bg-[var(--surface)] text-[var(--muted)]' : 'border-[var(--border)] bg-[var(--surface-elevated)]'} transition-colors`}
                                >
                                    <div className="min-w-0 flex-1">
                                        <div className="font-semibold text-sm truncate">
                                            {job.result_data?.original_filename || job.id}
                                        </div>
                                        <div className="text-xs text-[var(--muted)]">
                                            {formatDate(timestamp)}
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-2">
                                        {isExpired ? (
                                            <span className="text-xs bg-[var(--surface)] border border-[var(--border)] px-2 py-1 rounded text-[var(--muted)]">
                                                Expired
                                            </span>
                                        ) : (
                                            <>
                                                {job.status === 'completed' && publicUrl && (
                                                    <>
                                                        <a
                                                            className="text-xs btn-primary py-1.5 px-3 h-auto"
                                                            href={publicUrl}
                                                            download={job.result_data?.original_filename || 'processed.mp4'}
                                                        >
                                                            Download
                                                        </a>
                                                        <button
                                                            onClick={() => { onJobSelect(job); setShowPreview(true); }}
                                                            className="text-xs btn-secondary py-1.5 px-3 h-auto"
                                                        >
                                                            View
                                                        </button>
                                                    </>
                                                )}
                                                {/* Delete button */}
                                                {confirmDeleteId === job.id ? (
                                                    <div className="flex items-center gap-1">
                                                        <button
                                                            onClick={async () => {
                                                                setDeletingJobId(job.id);
                                                                try {
                                                                    await api.deleteJob(job.id);
                                                                    setConfirmDeleteId(null);
                                                                    // Refresh jobs list without page reload
                                                                    await onRefreshJobs();
                                                                } catch (err) {
                                                                    console.error('Delete failed:', err);
                                                                } finally {
                                                                    setDeletingJobId(null);
                                                                }
                                                            }}
                                                            disabled={deletingJobId === job.id}
                                                            className="text-xs px-2 py-1 rounded bg-[var(--danger)] text-white hover:bg-[var(--danger)]/80 disabled:opacity-50"
                                                        >
                                                            {deletingJobId === job.id ? '...' : '✓'}
                                                        </button>
                                                        <button
                                                            onClick={() => setConfirmDeleteId(null)}
                                                            className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:bg-white/5"
                                                        >
                                                            ✕
                                                        </button>
                                                    </div>
                                                ) : (
                                                    <button
                                                        onClick={() => setConfirmDeleteId(job.id)}
                                                        className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--danger)] hover:text-[var(--danger)] transition-colors"
                                                        title={t('deleteJob')}
                                                    >
                                                        🗑️
                                                    </button>
                                                )}
                                            </>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                <VideoModal
                    isOpen={showPreview}
                    onClose={() => setShowPreview(false)}
                    videoUrl={videoUrl || ''}
                />
            </div>
        </div >
    );
}
