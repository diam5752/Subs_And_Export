import React, { useState } from 'react';
import { useI18n } from '@/context/I18nContext';
import { api, ViralMetadataResponse } from '@/lib/api';

interface ViralIntelligenceProps {
    jobId: string;
}

export function ViralIntelligence({ jobId }: ViralIntelligenceProps) {
    const { t } = useI18n();
    const [loading, setLoading] = useState(false);
    const [metadata, setMetadata] = useState<ViralMetadataResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [copiedHook, setCopiedHook] = useState<string | null>(null);

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

    const copyToClipboard = async (text: string) => {
        try {
            await navigator.clipboard.writeText(text);
            setCopiedHook(text);
            setTimeout(() => setCopiedHook(null), 2000);
        } catch (err) {
            console.error('Failed to copy', err);
        }
    };

    if (!metadata && !loading) {
        return (
            <div className="mt-4">
                <button
                    onClick={handleGenerate}
                    className="btn-secondary w-full flex items-center justify-center gap-2"
                >
                    <span>✨</span> {t('viralGenerate')}
                </button>
                {error && <p className="text-[var(--danger)] text-sm mt-2 text-center">{error}</p>}
            </div>
        );
    }

    if (loading) {
        return (
            <div className="mt-4 flex flex-col items-center justify-center py-8 space-y-3 bg-[var(--surface-elevated)] rounded-xl border border-[var(--border)]">
                <div className="animate-spin text-2xl">⚡</div>
                <p className="text-[var(--muted)] animate-pulse">{t('viralAnalyzing')}</p>
            </div>
        );
    }

    if (!metadata) return null;

    return (
        <div className="mt-6 space-y-4 animate-fade-in">
            <h3 className="text-lg font-bold flex items-center gap-2">
                <span>🚀</span> {t('viralTitle')}
            </h3>

            {/* Hooks */}
            <div className="card bg-[var(--surface-elevated)] p-4 space-y-3">
                <h4 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider">{t('viralHooksLabel')}</h4>
                <div className="space-y-2">
                    {metadata.hooks.map((hook, i) => (
                        <button
                            key={i}
                            type="button"
                            onClick={() => copyToClipboard(hook)}
                            className="w-full text-left p-3 rounded-lg border border-[var(--border)] hover:border-[var(--accent)] cursor-pointer transition-colors bg-[var(--surface)] flex justify-between items-center group focus-visible:ring-2 focus-visible:ring-[var(--accent)] outline-none"
                        >
                            <span className="font-bold">{hook}</span>
                            <span className={`text-xs transition-opacity ${copiedHook === hook ? 'text-[var(--accent)] opacity-100' : 'text-[var(--muted)] opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100'}`}>
                                {copiedHook === hook ? '✓' : t('viralCopy')}
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
                        onClick={() => copyToClipboard(`${metadata.caption_hook}\n\n${metadata.caption_body}\n\n${metadata.cta}\n\n${metadata.hashtags.join(' ')}`)}
                        className="text-xs text-[var(--accent)] hover:underline"
                    >
                        {t('viralCopyFull')}
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
    );
}
