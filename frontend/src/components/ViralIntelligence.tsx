import React, { useEffect, useRef, useState } from 'react';
import { useI18n } from '@/context/I18nContext';
import { api, FactCheckResponse, SocialCopyResponse } from '@/lib/api';
import { InfoTooltip } from '@/components/InfoTooltip';
import { usePoints } from '@/context/PointsContext';
import { TokenIcon } from '@/components/icons';
import { FACT_CHECK_COST, SOCIAL_COPY_COST, formatPoints } from '@/lib/points';

interface ViralIntelligenceProps {
    jobId: string;
}

function CopyButton({ text, label }: { text: string; label: string }) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async (e: React.MouseEvent) => {
        e.stopPropagation();
        try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy', err);
        }
    };

    return (
        <button
            type="button"
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-medium bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 transition-all text-white/50 hover:text-white"
            aria-label={copied ? "Copied" : `Copy ${label}`}
        >
            {copied ? (
                <>
                    <svg className="w-3 h-3 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    <span className="text-emerald-400">Copied</span>
                </>
            ) : (
                <>
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                    <span>Copy</span>
                </>
            )}
        </button>
    );
}

export function ViralIntelligence({ jobId }: ViralIntelligenceProps) {
    const { t, locale } = useI18n();
    const { setBalance } = usePoints();
    const activeJobIdRef = useRef(jobId);

    // Fact Check State
    const [checkingFacts, setCheckingFacts] = useState(false);
    const [factCheckResult, setFactCheckResult] = useState<FactCheckResponse | null>(null);

    // Social Copy State
    const [generatingCopy, setGeneratingCopy] = useState(false);
    const [socialCopyResult, setSocialCopyResult] = useState<SocialCopyResponse | null>(null);

    const [error, setError] = useState<string | null>(null);

    const loading = checkingFacts || generatingCopy;

    useEffect(() => {
        activeJobIdRef.current = jobId;
        setCheckingFacts(false);
        setGeneratingCopy(false);
        setFactCheckResult(null);
        setSocialCopyResult(null);
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

    const handleSocialCopy = async () => {
        const requestJobId = jobId;
        setGeneratingCopy(true);
        setError(null);
        try {
            const result = await api.socialCopy(requestJobId);
            if (activeJobIdRef.current !== requestJobId) return;
            setSocialCopyResult(result);
            if (typeof result.balance === 'number') {
                setBalance(result.balance);
            }
        } catch (err: unknown) {
            if (activeJobIdRef.current !== requestJobId) return;
            const message = err instanceof Error ? err.message : 'Failed to generate social copy';
            setError(message);
        } finally {
            if (activeJobIdRef.current !== requestJobId) return;
            setGeneratingCopy(false);
        }
    };

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
                {/* Fact Check Button */}
                {!factCheckResult && !loading && (
                    <div className="relative group/btn">
                        <button
                            onClick={handleFactCheck}
                            disabled={loading}
                            className="w-full group relative flex flex-col items-center justify-center gap-3 py-6 px-4 rounded-[2rem] bg-white/5 hover:bg-white/10 backdrop-blur-2xl border border-white/10 transition-all duration-300 hover:scale-[1.02] active:scale-[0.98] shadow-lg hover:shadow-xl hover:shadow-emerald-500/10"
                        >
                            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-emerald-400/20 to-teal-400/20 flex items-center justify-center text-emerald-300 shadow-inner mb-1 group-hover:scale-110 group-hover:bg-gradient-to-br group-hover:from-emerald-400 group-hover:to-teal-400 group-hover:text-white transition-all duration-300">
                                <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                                    <path d="M9 12l2 2 4-4" />
                                </svg>
                            </div>
                            <div className="text-center">
                                <span className="block text-sm font-medium text-white/90 group-hover:text-white">{t('viralVerifyFacts')}</span>
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
                                    <div className="font-semibold text-[11px]">{t('viralVerifyFacts')}</div>
                                    <p className="text-[var(--muted)] leading-snug">{t('factCheckTooltip')}</p>
                                </div>
                            </InfoTooltip>
                        </div>
                    </div>
                )}

                {/* Social Copy Button */}
                {!socialCopyResult && !loading && (
                    <div className="relative group/btn">
                        <button
                            onClick={handleSocialCopy}
                            disabled={loading}
                            className="w-full group relative flex flex-col items-center justify-center gap-3 py-6 px-4 rounded-[2rem] bg-white/5 hover:bg-white/10 backdrop-blur-2xl border border-white/10 transition-all duration-300 hover:scale-[1.02] active:scale-[0.98] shadow-lg hover:shadow-xl hover:shadow-purple-500/10"
                        >
                            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-purple-400/20 to-pink-400/20 flex items-center justify-center text-purple-300 shadow-inner mb-1 group-hover:scale-110 group-hover:bg-gradient-to-br group-hover:from-purple-400 group-hover:to-pink-400 group-hover:text-white transition-all duration-300">
                                {/* Wand / Sparkles Icon */}
                                <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M15 4V2" />
                                    <path d="M15 16v-2" />
                                    <path d="M8 9h2" />
                                    <path d="M20 9h2" />
                                    <path d="M17.8 11.8L19 13" />
                                    <path d="M10.6 6.6L12 8" />
                                    <path d="M4.8 13.6l1.4 1.4" />
                                    <path d="M11.9 16.3l1.4 1.4" />
                                    <path d="M7.1 21L2.1 16l2.8-2.8c.8-.8 2.1-.8 2.8 0L9.9 15.4c.8.8.8 2.1 0 2.8L7.1 21z" />
                                </svg>
                            </div>
                            <div className="text-center">
                                <span className="block text-sm font-medium text-white/90 group-hover:text-white">{t('viralGenerateMetadata')}</span>
                                <div className="flex items-center justify-center gap-1.5 opacity-80 mt-1">
                                    <TokenIcon className="w-3.5 h-3.5" />
                                    <span className="text-xs font-semibold text-white/70">
                                        {formatPoints(SOCIAL_COPY_COST)}
                                    </span>
                                </div>
                            </div>
                        </button>
                        <div className="absolute top-3 right-3">
                            <InfoTooltip ariaLabel={t('viralGenerateTooltipData')}>
                                <div className="space-y-1">
                                    <div className="font-semibold text-[11px]">{t('viralGenerateMetadata')}</div>
                                    <p className="text-[var(--muted)] leading-snug">{t('viralGenerateDesc')}</p>
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

            {loading && (
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
                        {checkingFacts ? t('checkingFacts') : t('viralAnalyzing')}
                    </p>
                </div>
            )}

            {/* Fact Check Results */}
            {factCheckResult && (
                <div className="space-y-5 animate-fade-in">
                    {/* Header */}
                    <div className="flex items-center justify-between px-2">
                        <h4 className="text-xs font-semibold text-white/40 uppercase tracking-widest pl-2 flex items-center gap-2">
                            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                            {t('factReport')}
                        </h4>
                        <button onClick={() => setFactCheckResult(null)} className="px-3 py-1 rounded-full bg-white/5 hover:bg-white/10 text-xs text-white/60 hover:text-white transition-colors backdrop-blur-md">{t('closeLabel')}</button>
                    </div>

                    {/* Truth Score Card */}
                    <div className="p-6 rounded-[2rem] bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 backdrop-blur-2xl shadow-2xl">
                        <div className="flex items-center justify-between gap-6">
                            {/* Score Circle */}
                            <div className="relative">
                                <svg className="w-24 h-24 -rotate-90" viewBox="0 0 100 100">
                                    <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="8" />
                                    <circle
                                        cx="50" cy="50" r="42" fill="none"
                                        stroke={factCheckResult.truth_score >= 80 ? '#34d399' : factCheckResult.truth_score >= 50 ? '#fbbf24' : '#f87171'}
                                        strokeWidth="8"
                                        strokeLinecap="round"
                                        strokeDasharray={`${factCheckResult.truth_score * 2.64} 264`}
                                        className="transition-all duration-1000"
                                    />
                                </svg>
                                <div className="absolute inset-0 flex flex-col items-center justify-center">
                                    <span className="text-2xl font-bold text-white">{factCheckResult.truth_score}</span>
                                    <span className="text-[10px] text-white/50 uppercase tracking-wide">{t('scoreLabel')}</span>
                                </div>
                            </div>

                            {/* Stats */}
                            <div className="flex-1 grid grid-cols-2 gap-4">
                                <div className="p-4 rounded-2xl bg-white/5 border border-white/5">
                                    <div className="text-2xl font-bold text-white">{factCheckResult.claims_checked}</div>
                                    <div className="text-[10px] text-white/40 uppercase tracking-wide mt-1">{t('claimsCheckedLabel')}</div>
                                </div>
                                <div className="p-4 rounded-2xl bg-white/5 border border-white/5">
                                    <div className="text-2xl font-bold text-emerald-400">{factCheckResult.supported_claims_pct}%</div>
                                    <div className="text-[10px] text-white/40 uppercase tracking-wide mt-1">{t('supportedLabel')}</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {factCheckResult.items.length === 0 ? (
                        <div className="p-6 rounded-[2rem] bg-emerald-500/5 border border-emerald-500/10 backdrop-blur-xl text-emerald-200/90 text-sm text-center font-medium shadow-lg flex flex-col items-center gap-3">
                            <div className="w-10 h-10 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400">
                                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5" /></svg>
                            </div>
                            <span className="text-base">{t('allVerified')}</span>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {factCheckResult.items.map((item, i) => (
                                <div key={i} className="rounded-[2rem] bg-white/5 border border-white/10 backdrop-blur-md overflow-hidden transition-all duration-300 hover:bg-white/[0.07]">
                                    {/* Item Header */}
                                    <div className="p-5 space-y-4">
                                        {/* Severity & Confidence Row */}
                                        <div className="flex items-center gap-3">
                                            <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide ${item.severity === 'major' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                                                item.severity === 'medium' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
                                                    'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                                                }`}>
                                                {t(item.severity as any)}
                                            </span>
                                            <div className="flex items-center gap-1.5 text-white/40">
                                                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83" /></svg>
                                                <span className="text-[10px] font-medium">{t('confidenceLabel', { percent: item.confidence })}</span>
                                            </div>
                                        </div>

                                        {/* Mistake */}
                                        <div className="flex gap-4">
                                            <div className="shrink-0 w-8 h-8 rounded-full bg-red-500/10 flex items-center justify-center text-red-400">
                                                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                                            </div>
                                            <div className="flex-1">
                                                <div className="text-[10px] font-medium text-red-400 mb-1 uppercase tracking-wide">{t('inaccuracyLabel')}</div>
                                                <p className="text-white/80 text-[15px] leading-relaxed">&quot;{locale === 'el' ? item.mistake_el : item.mistake_en}&quot;</p>
                                            </div>
                                        </div>

                                        {/* Correction */}
                                        <div className="pl-12">
                                            <div className="p-4 rounded-xl bg-emerald-500/5 border border-emerald-500/10">
                                                <div className="text-[10px] font-medium text-emerald-400 mb-1 uppercase tracking-wide">{t('correctionLabel')}</div>
                                                <p className="text-white/90 text-[15px] font-medium leading-relaxed">{locale === 'el' ? item.correction_el : item.correction_en}</p>
                                                <p className="text-xs text-white/40 mt-3 pt-3 border-t border-white/5 leading-relaxed">{locale === 'el' ? item.explanation_el : item.explanation_en}</p>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Evidence Section */}
                                    {(item.real_life_example_el || item.real_life_example_en || item.scientific_evidence_el || item.scientific_evidence_en) && (
                                        <div className="px-5 pb-5 pt-0 space-y-3">
                                            {/* Real-life Example */}
                                            {(locale === 'el' ? item.real_life_example_el : item.real_life_example_en) && (
                                                <div className="p-4 rounded-xl bg-amber-500/5 border border-amber-500/10">
                                                    <div className="flex items-center gap-2 mb-2">
                                                        <span className="text-lg">💡</span>
                                                        <span className="text-[10px] font-medium text-amber-400 uppercase tracking-wide">{t('realWorldExampleLabel')}</span>
                                                    </div>
                                                    <p className="text-white/70 text-sm leading-relaxed">{locale === 'el' ? item.real_life_example_el : item.real_life_example_en}</p>
                                                </div>
                                            )}

                                            {/* Scientific Evidence */}
                                            {(locale === 'el' ? item.scientific_evidence_el : item.scientific_evidence_en) && (
                                                <div className="p-4 rounded-xl bg-blue-500/5 border border-blue-500/10">
                                                    <div className="flex items-center gap-2 mb-2">
                                                        <span className="text-lg">🔬</span>
                                                        <span className="text-[10px] font-medium text-blue-400 uppercase tracking-wide">{t('scientificEvidenceLabel')}</span>
                                                    </div>
                                                    <p className="text-white/70 text-sm leading-relaxed">{locale === 'el' ? item.scientific_evidence_el : item.scientific_evidence_en}</p>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Social Copy Results */}
            {socialCopyResult && (
                <div className="space-y-4 animate-fade-in">
                    <div className="flex items-center justify-between px-2">
                        <h4 className="text-xs font-semibold text-white/40 uppercase tracking-widest pl-2 flex items-center gap-2">
                            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 4V2" /><path d="M15 16v-2" /></svg>
                            {t('metadataLabel')}
                        </h4>
                        <button onClick={() => setSocialCopyResult(null)} className="px-3 py-1 rounded-full bg-white/5 hover:bg-white/10 text-xs text-white/60 hover:text-white transition-colors backdrop-blur-md">{t('closeLabel')}</button>
                    </div>

                    <div className="p-5 rounded-[2rem] bg-white/5 border border-white/10 backdrop-blur-md hover:bg-white/10 transition-colors space-y-4">
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-xs font-medium text-purple-400 uppercase tracking-wide">{t('titleLabel')}</label>
                                <CopyButton text={locale === 'el' ? socialCopyResult.social_copy.title_el : socialCopyResult.social_copy.title_en} label={t('titleLabel')} />
                            </div>
                            <div className="p-3 rounded-xl bg-black/20 border border-white/5 text-white/90 text-sm font-medium">
                                {locale === 'el' ? socialCopyResult.social_copy.title_el : socialCopyResult.social_copy.title_en}
                            </div>
                        </div>
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-xs font-medium text-purple-400 uppercase tracking-wide">{t('descriptionLabel')}</label>
                                <CopyButton text={locale === 'el' ? socialCopyResult.social_copy.description_el : socialCopyResult.social_copy.description_en} label={t('descriptionLabel')} />
                            </div>
                            <div className="p-3 rounded-xl bg-black/20 border border-white/5 text-white/80 text-sm leading-relaxed whitespace-pre-wrap">
                                {locale === 'el' ? socialCopyResult.social_copy.description_el : socialCopyResult.social_copy.description_en}
                            </div>
                        </div>
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-xs font-medium text-purple-400 uppercase tracking-wide">{t('hashtagsLabel')}</label>
                                <CopyButton text={socialCopyResult.social_copy.hashtags.join(' ')} label={t('hashtagsLabel')} />
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {socialCopyResult.social_copy.hashtags.map((tag, i) => (
                                    <span key={i} className="px-2 py-1 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs">
                                        {tag}
                                    </span>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            )}

        </div>
    );
}
