import React, { useEffect, useRef, useState } from 'react';
import { useI18n } from '@/context/I18nContext';
import { api, FactCheckResponse } from '@/lib/api';
import { InfoTooltip } from '@/components/InfoTooltip';
import { usePoints } from '@/context/PointsContext';
import { TokenIcon } from '@/components/icons';
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
    const [factCheckResult, setFactCheckResult] = useState<FactCheckResponse | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        activeJobIdRef.current = jobId;
        setLoading(false);
        setCheckingFacts(false);
        setFactCheckResult(null);
        setError(null);
    }, [jobId]);

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



    return (
        <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">


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
                                <div className="flex items-center justify-center gap-1.5 opacity-80 mt-1">
                                    <TokenIcon className="w-3.5 h-3.5" />
                                    <span className="text-xs font-semibold text-white/70">
                                        {formatPoints(FACT_CHECK_COST)}
                                    </span>
                                </div>
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


        </div>
    );
}
