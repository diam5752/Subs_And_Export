import React, { useState } from 'react';
import { useI18n } from '@/context/I18nContext';
import { api, ViralMetadataResponse, FactCheckResponse } from '@/lib/api';

interface ViralIntelligenceProps {
    jobId: string;
}

export function ViralIntelligence({ jobId }: ViralIntelligenceProps) {
    const { t } = useI18n();
    const [loading, setLoading] = useState(false);
    const [checkingFacts, setCheckingFacts] = useState(false);
    const [metadata, setMetadata] = useState<ViralMetadataResponse | null>(null);
    const [factCheckResult, setFactCheckResult] = useState<FactCheckResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
    const [copiedFull, setCopiedFull] = useState(false);

    const handleGenerate = async () => {
        setLoading(true);
        setError(null);
        try {
            const result = await api.generateViralMetadata(jobId);
            setMetadata(result);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : 'Failed to generate metadata';
            setError(message);
        } finally {
            setLoading(false);
        }
    };

    const handleFactCheck = async () => {
        setCheckingFacts(true);
        setError(null);
        try {
            const result = await api.factCheck(jobId);
            setFactCheckResult(result);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : 'Failed to fact check';
            setError(message);
        } finally {
            setCheckingFacts(false);
        }
    };

    const copyToClipboard = async (text: string, index?: number, isFull?: boolean) => {
        try {
            await navigator.clipboard.writeText(text);
            if (isFull) {
                setCopiedFull(true);
                setTimeout(() => setCopiedFull(false), 2000);
            } else if (index !== undefined) {
                setCopiedIndex(index);
                setTimeout(() => setCopiedIndex(null), 2000);
            }
        } catch (err) {
            console.error('Failed to copy', err);
        }
    };

    return (
        <div className="mt-6 space-y-4 animate-fade-in border-t border-[var(--border)] pt-6">
            <h3 className="text-lg font-bold flex items-center gap-2">
                <span>🤖</span> {t('viralIntelligence') || 'AI Intelligence'}
            </h3>

            <div className="flex gap-2">
                {!metadata && !loading && (
                    <button
                        onClick={handleGenerate}
                        disabled={loading || checkingFacts}
                        className="btn-secondary flex-1 flex items-center justify-center gap-2 py-2"
                    >
                        <span>✨</span> {t('viralGenerate')}
                    </button>
                )}

                {!factCheckResult && !checkingFacts && (
                    <button
                        onClick={handleFactCheck}
                        disabled={loading || checkingFacts}
                        className="btn-secondary flex-1 flex items-center justify-center gap-2 py-2 border-emerald-500/30 hover:border-emerald-500/60 bg-emerald-500/5 hover:bg-emerald-500/10 text-emerald-400"
                    >
                        <span>✅</span> {t('factCheck') || 'Fact Check'}
                    </button>
                )}
            </div>

            {error && <p className="text-[var(--danger)] text-sm mt-2 text-center">{error}</p>}

            {(loading || checkingFacts) && (
                <div className="flex flex-col items-center justify-center py-8 space-y-3 bg-[var(--surface-elevated)] rounded-xl border border-[var(--border)]">
                    <div className="animate-spin text-2xl">⚡</div>
                    <p className="text-[var(--muted)] animate-pulse">
                        {loading ? t('viralAnalyzing') : (t('checkingFacts') || 'Verifying accuracy...')}
                    </p>
                </div>
            )}

            {/* Fact Check Results */}
            {factCheckResult && (
                <div className="space-y-3 animate-fade-in">
                    <div className="flex items-center justify-between">
                        <h4 className="text-sm font-semibold text-emerald-400 uppercase tracking-wider flex items-center gap-2">
                            <span>🛡️</span> {t('factCheckResults') || 'Fact Check Report'}
                        </h4>
                        <button onClick={() => setFactCheckResult(null)} className="text-xs opacity-50 hover:opacity-100">Clear</button>
                    </div>

                    {factCheckResult.items.length === 0 ? (
                        <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-sm text-center">
                            ✅ No significant factual errors found.
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {factCheckResult.items.map((item, i) => (
                                <div key={i} className="card bg-[var(--surface-elevated)] p-4 border-l-4 border-l-[var(--danger)]">
                                    <div className="mb-2">
                                        <span className="text-xs font-bold text-[var(--danger)] uppercase">Mistake</span>
                                        <p className="text-sm italic opacity-80 mt-0.5">&quot;{item.mistake}&quot;</p>
                                    </div>
                                    <div className="mb-2">
                                        <span className="text-xs font-bold text-emerald-400 uppercase">Correction</span>
                                        <p className="text-sm font-medium mt-0.5">{item.correction}</p>
                                    </div>
                                    <div>
                                        <span className="text-xs font-bold text-[var(--accent)] uppercase">Why</span>
                                        <p className="text-xs opacity-70 mt-0.5">{item.explanation}</p>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Viral Metadata Results */}
            {metadata && (
                <div className="space-y-4 animate-fade-in">
                    <div className="flex items-center justify-between">
                        <h4 className="text-sm font-semibold text-[var(--accent)] uppercase tracking-wider flex items-center gap-2">
                            <span>🚀</span> {t('viralTitle')}
                        </h4>
                        <button onClick={() => setMetadata(null)} className="text-xs opacity-50 hover:opacity-100">Clear</button>
                    </div>

                    {/* Hooks */}
                    <div className="card bg-[var(--surface-elevated)] p-4 space-y-3">
                        <h4 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider">{t('viralHooksLabel')}</h4>
                        <div className="space-y-2">
                            {metadata.hooks.map((hook, i) => (
                                <button
                                    key={i}
                                    type="button"
                                    onClick={() => copyToClipboard(hook, i)}
                                    className="w-full text-left p-3 rounded-lg border border-[var(--border)] hover:border-[var(--accent)] cursor-pointer transition-colors bg-[var(--surface)] flex justify-between items-center group focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none"
                                    aria-label={`${t('viralCopy')}: ${hook}`}
                                >
                                    <span className="font-bold">{hook}</span>
                                    <span className={`text-xs font-medium transition-all ${copiedIndex === i
                                        ? 'text-emerald-500 opacity-100'
                                        : 'text-[var(--muted)] opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100'
                                        }`}>
                                        {copiedIndex === i ? t('viralCopied') : t('viralCopy')}
                                    </span>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Caption */}
                    <div className="card bg-[var(--surface-elevated)] p-4 space-y-3">
                        <div className="flex justify-between items-center">
                            <h4 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider">{t('viralCaptionLabel')}</h4>
                            <button
                                onClick={() => copyToClipboard(`${metadata.caption_hook}\n\n${metadata.caption_body}\n\n${metadata.cta}\n\n${metadata.hashtags.join(' ')}`, undefined, true)}
                                className={`text-xs font-medium transition-colors hover:underline ${copiedFull ? 'text-emerald-500' : 'text-[var(--accent)]'}`}
                            >
                                {copiedFull ? t('viralCopied') : t('viralCopyFull')}
                            </button>
                        </div>
                        <div className="space-y-4 text-sm">
                            <p className="font-bold">{metadata.caption_hook}</p>
                            <p className="whitespace-pre-wrap">{metadata.caption_body}</p>
                            <p className="font-medium text-[var(--foreground)]">{metadata.cta}</p>
                            <div className="flex flex-wrap gap-2 text-[var(--accent)]">
                                {metadata.hashtags.map(tag => (
                                    <span key={tag}>{tag}</span>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
