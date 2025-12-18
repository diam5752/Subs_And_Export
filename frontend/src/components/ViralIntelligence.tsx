import React, { useEffect, useRef, useState } from 'react';
import { useI18n } from '@/context/I18nContext';
import { api, ViralMetadataResponse, FactCheckResponse } from '@/lib/api';
import { InfoTooltip } from '@/components/InfoTooltip';
import { usePoints } from '@/context/PointsContext';
import { FACT_CHECK_COST, formatPoints } from '@/lib/points';

interface ViralIntelligenceProps {
    jobId: string;
}

export function ViralIntelligence({ jobId }: ViralIntelligenceProps) {
    const { t } = useI18n();
    const { setBalance } = usePoints();
    const activeJobIdRef = useRef(jobId);
    const [loading, setLoading] = useState(false);
    const [checkingFacts, setCheckingFacts] = useState(false);
    const [metadata, setMetadata] = useState<ViralMetadataResponse | null>(null);
    const [factCheckResult, setFactCheckResult] = useState<FactCheckResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
    const [copiedFull, setCopiedFull] = useState(false);

    useEffect(() => {
        activeJobIdRef.current = jobId;
        setLoading(false);
        setCheckingFacts(false);
        setMetadata(null);
        setFactCheckResult(null);
        setError(null);
        setCopiedIndex(null);
        setCopiedFull(false);
    }, [jobId]);

    const handleGenerate = async () => {
        const requestJobId = jobId;
        setLoading(true);
        setError(null);
        try {
            const result = await api.generateViralMetadata(requestJobId);
            if (activeJobIdRef.current !== requestJobId) return;
            setMetadata(result);
        } catch (err: unknown) {
            if (activeJobIdRef.current !== requestJobId) return;
            const message = err instanceof Error ? err.message : 'Failed to generate metadata';
            setError(message);
        } finally {
            if (activeJobIdRef.current !== requestJobId) return;
            setLoading(false);
        }
    };

    const handleFactCheck = async () => {
        const requestJobId = jobId;
        setCheckingFacts(true);
        setError(null);
        try {
            const result = await api.factCheck(requestJobId);
            if (activeJobIdRef.current !== requestJobId) return;
            setFactCheckResult(result);
            if (typeof result.balance === 'number') {
                setBalance(result.balance);
            }
        } catch (err: unknown) {
            if (activeJobIdRef.current !== requestJobId) return;
            const message = err instanceof Error ? err.message : 'Failed to fact check';
            setError(message);
        } finally {
            if (activeJobIdRef.current !== requestJobId) return;
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
        <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
                {!metadata && !loading && (
                    <div className="relative group/btn">
                        <button
                            onClick={handleGenerate}
                            disabled={loading || checkingFacts}
                            className="w-full group relative flex flex-col items-center justify-center gap-3 py-6 px-4 rounded-[2rem] bg-white/5 hover:bg-white/10 backdrop-blur-2xl border border-white/10 transition-all duration-300 hover:scale-[1.02] active:scale-[0.98] shadow-lg hover:shadow-xl hover:shadow-purple-500/10"
                        >
                            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-indigo-400/20 to-purple-400/20 flex items-center justify-center text-indigo-300 shadow-inner mb-1 group-hover:scale-110 group-hover:bg-gradient-to-br group-hover:from-indigo-400 group-hover:to-purple-400 group-hover:text-white transition-all duration-300">
                                {/* Magic Spark Icon */}
                                <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                                    <path d="M12 2v0" />
                                </svg>
                            </div>
                            <div className="text-center">
                                <span className="block text-sm font-medium text-white/90 group-hover:text-white">{t('viralGenerate') || 'Generate Metadata'}</span>
                                <span className="block text-xs text-white/40 mt-1">{t('creditsFree') || 'Free'}</span>
                            </div>
                        </button>
                        <div className="absolute top-3 right-3">
                            <InfoTooltip ariaLabel={t('viralGenerateTooltip')}>
                                <div className="space-y-1">
                                    <div className="font-semibold text-[11px]">{t('viralGenerate') || 'Generate Metadata'}</div>
                                    <p className="text-[var(--muted)] leading-snug">{t('viralGenerateTooltip')}</p>
                                </div>
                            </InfoTooltip>
                        </div>
                    </div>
                )}

                {!factCheckResult && !checkingFacts && (
                    <div className="relative group/btn">
                        <button
                            onClick={handleFactCheck}
                            disabled={loading || checkingFacts}
                            className="w-full group relative flex flex-col items-center justify-center gap-3 py-6 px-4 rounded-[2rem] bg-white/5 hover:bg-white/10 backdrop-blur-2xl border border-white/10 transition-all duration-300 hover:scale-[1.02] active:scale-[0.98] shadow-lg hover:shadow-xl hover:shadow-emerald-500/10"
                        >
                            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-emerald-400/20 to-teal-400/20 flex items-center justify-center text-emerald-300 shadow-inner mb-1 group-hover:scale-110 group-hover:bg-gradient-to-br group-hover:from-emerald-400 group-hover:to-teal-400 group-hover:text-white transition-all duration-300">
                                {/* Shield Check Icon */}
                                <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                                    <path d="M9 12l2 2 4-4" />
                                </svg>
                            </div>
                            <div className="text-center">
                                <span className="block text-sm font-medium text-white/90 group-hover:text-white">{t('factCheck') || 'Verify Facts'}</span>
                                <span className="block text-xs text-white/40 mt-1">
                                    {(t('creditsCostInline') || '{cost} credits').replace('{cost}', formatPoints(FACT_CHECK_COST))}
                                </span>
                            </div>
                        </button>
                        <div className="absolute top-3 right-3">
                            <InfoTooltip ariaLabel={t('factCheckTooltip')}>
                                <div className="space-y-1">
                                    <div className="font-semibold text-[11px]">{t('factCheck') || 'Verify Facts'}</div>
                                    <p className="text-[var(--muted)] leading-snug">{t('factCheckTooltip')}</p>
                                </div>
                            </InfoTooltip>
                        </div>
                    </div>
                )}
            </div>

            {error && (
                <div className="p-4 rounded-[1.5rem] bg-red-500/10 backdrop-blur-xl border border-red-500/10 text-red-200 text-sm text-center font-medium">
                    {error}
                </div>
            )}

            {(loading || checkingFacts) && (
                <div className="flex flex-col items-center justify-center py-16 space-y-4 rounded-[2.5rem] bg-white/5 border border-white/10 backdrop-blur-2xl shadow-2xl">
                    <div className="relative">
                        <div className="w-12 h-12 rounded-full border-2 border-white/10 border-t-white animate-spin" />
                        <div className="absolute inset-0 flex items-center justify-center">
                            <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                            </svg>
                        </div>
                    </div>
                    <p className="text-white/60 font-medium tracking-wide text-sm animate-pulse">
                        {loading ? 'Processing Content...' : 'Verifying Accuracy...'}
                    </p>
                </div>
            )}

            {/* Fact Check Results - VisionOS Card */}
            {factCheckResult && (
                <div className="space-y-4 animate-fade-in">
                    <div className="flex items-center justify-between px-2">
                        <h4 className="text-xs font-semibold text-white/40 uppercase tracking-widest pl-2 flex items-center gap-2">
                            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                            Report
                        </h4>
                        <button onClick={() => setFactCheckResult(null)} className="px-3 py-1 rounded-full bg-white/5 hover:bg-white/10 text-xs text-white/60 hover:text-white transition-colors backdrop-blur-md">Close</button>
                    </div>

                    {factCheckResult.items.length === 0 ? (
                        <div className="p-6 rounded-[2rem] bg-emerald-500/5 border border-emerald-500/10 backdrop-blur-xl text-emerald-200/90 text-sm text-center font-medium shadow-lg flex flex-col items-center gap-3">
                            <div className="w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400">
                                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5" /></svg>
                            </div>
                            <span>No factual errors detected by the system.</span>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {factCheckResult.items.map((item, i) => (
                                <div key={i} className="p-5 rounded-[2rem] bg-white/5 border border-white/10 backdrop-blur-md hover:bg-white/10 transition-colors">
                                    <div className="space-y-4">
                                        <div className="flex gap-4">
                                            <div className="shrink-0 w-8 h-8 rounded-full bg-red-500/10 flex items-center justify-center text-red-400">
                                                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                                            </div>
                                            <div>
                                                <div className="text-xs font-medium text-red-400 mb-1 opacity-80 uppercase tracking-wide">Inaccuracy Detected</div>
                                                <p className="text-white/80 text-[15px] leading-relaxed">&quot;{item.mistake}&quot;</p>
                                            </div>
                                        </div>
                                        <div className="pl-12">
                                            <div className="p-4 rounded-xl bg-emerald-500/5 border border-emerald-500/10">
                                                <div className="text-xs font-medium text-emerald-400 mb-1 opacity-80 uppercase tracking-wide">Correction</div>
                                                <p className="text-white/90 text-[15px] font-medium leading-relaxed">{item.correction}</p>
                                                <p className="text-xs text-white/40 mt-3 pt-3 border-t border-white/5 leading-relaxed">{item.explanation}</p>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Viral Metadata Results - VisionOS Stack */}
            {metadata && (
                <div className="space-y-6 animate-fade-in">
                    <div className="flex items-center justify-between px-2">
                        <h4 className="text-xs font-semibold text-white/40 uppercase tracking-widest pl-2 flex items-center gap-2">
                            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" /></svg>
                            Generated Output
                        </h4>
                        <button onClick={() => setMetadata(null)} className="px-3 py-1 rounded-full bg-white/5 hover:bg-white/10 text-xs text-white/60 hover:text-white transition-colors backdrop-blur-md">Close</button>
                    </div>

                    {/* Hooks - Glass List */}
                    <div className="space-y-2">
                        {metadata.hooks.map((hook, i) => (
                            <button
                                key={i}
                                type="button"
                                onClick={() => copyToClipboard(hook, i)}
                                className="group w-full text-left p-5 rounded-[1.5rem] border border-white/5 hover:border-white/20 bg-white/5 hover:bg-white/10 cursor-pointer transition-all flex justify-between items-center backdrop-blur-md active:scale-[0.99] shadow-sm hover:shadow-md"
                            >
                                <span className="font-medium text-[15px] text-white/90 pr-8 leading-snug">{hook}</span>
                                <div className={`w-8 h-8 shrink-0 rounded-full flex items-center justify-center transition-all ${copiedIndex === i
                                    ? 'bg-emerald-500 text-white scale-100'
                                    : 'bg-white/10 text-white/40 scale-75 group-hover:scale-100 group-hover:bg-white/20'
                                    }`}>
                                    {copiedIndex === i ? (
                                        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 13l4 4L19 7" /></svg>
                                    ) : (
                                        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
                                    )}
                                </div>
                            </button>
                        ))}
                    </div>

                    {/* Caption - Glass Card */}
                    <div className="p-6 rounded-[2.5rem] bg-white/5 border border-white/10 backdrop-blur-xl shadow-2xl relative overflow-hidden group hover:bg-white/[0.07] transition-colors">
                        <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-white/10 to-transparent" />

                        <div className="flex justify-between items-center mb-6">
                            <span className="text-xs font-bold text-white/30 uppercase tracking-widest">Caption & Tags</span>
                            <button
                                onClick={() => copyToClipboard(`${metadata.caption_hook}\n\n${metadata.caption_body}\n\n${metadata.cta}\n\n${metadata.hashtags.join(' ')}`, undefined, true)}
                                className={`text-xs px-3 py-1.5 rounded-full transition-all font-medium flex items-center gap-2 ${copiedFull ? 'bg-emerald-500/20 text-emerald-300' : 'bg-white/10 text-white/60 hover:bg-white/20 hover:text-white'}`}
                            >
                                {copiedFull ? (
                                    <>
                                        <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 13l4 4L19 7" /></svg>
                                        Copied
                                    </>
                                ) : (
                                    <>
                                        <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
                                        Copy All
                                    </>
                                )}
                            </button>
                        </div>

                        <div className="space-y-4 text-white/80 text-[15px] leading-relaxed font-light">
                            <p className="font-semibold text-white text-lg">{metadata.caption_hook}</p>
                            <p className="whitespace-pre-wrap opacity-90">{metadata.caption_body}</p>
                            <p className="font-medium text-white">{metadata.cta}</p>
                            <div className="flex flex-wrap gap-2 pt-4">
                                {metadata.hashtags.map(tag => (
                                    <span key={tag} className="text-indigo-300 text-xs px-2.5 py-1 rounded-md bg-indigo-500/10 border border-indigo-500/10">{tag}</span>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
