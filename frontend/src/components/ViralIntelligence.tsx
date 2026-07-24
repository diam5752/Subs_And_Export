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
            className="flex min-h-11 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-white px-3 text-[11px] font-semibold text-[var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--foreground)]"
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
    return <ViralIntelligenceSession key={jobId} jobId={jobId} />;
}

function ViralIntelligenceSession({ jobId }: ViralIntelligenceProps) {
    const { t, locale } = useI18n();
    const { setBalance } = usePoints();
    const isActiveRef = useRef(true);

    // Fact Check State
    const [checkingFacts, setCheckingFacts] = useState(false);
    const [factCheckResult, setFactCheckResult] = useState<FactCheckResponse | null>(null);

    // Social Copy State
    const [generatingCopy, setGeneratingCopy] = useState(false);
    const [socialCopyResult, setSocialCopyResult] = useState<SocialCopyResponse | null>(null);

    const [error, setError] = useState<string | null>(null);

    const loading = checkingFacts || generatingCopy;

    useEffect(() => () => {
        isActiveRef.current = false;
    }, []);

    const handleFactCheck = async () => {
        const requestJobId = jobId;
        setCheckingFacts(true);
        setError(null);
        try {
            const result = await api.factCheck(requestJobId);
            if (!isActiveRef.current) return;
            setFactCheckResult(result);
            if (typeof result.balance === 'number') {
                setBalance(result.balance);
            }
        } catch (err: unknown) {
            if (!isActiveRef.current) return;
            const message = err instanceof Error ? err.message : 'Failed to fact check';
            setError(message);
        } finally {
            if (!isActiveRef.current) return;
            setCheckingFacts(false);
        }
    };

    const handleSocialCopy = async () => {
        const requestJobId = jobId;
        setGeneratingCopy(true);
        setError(null);
        try {
            const result = await api.socialCopy(requestJobId);
            if (!isActiveRef.current) return;
            setSocialCopyResult(result);
            if (typeof result.balance === 'number') {
                setBalance(result.balance);
            }
        } catch (err: unknown) {
            if (!isActiveRef.current) return;
            const message = err instanceof Error ? err.message : 'Failed to generate social copy';
            setError(message);
        } finally {
            if (!isActiveRef.current) return;
            setGeneratingCopy(false);
        }
    };

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {/* Fact Check Button */}
                {!factCheckResult && !loading && (
                    <div className="relative group/btn">
                        <button
                            onClick={handleFactCheck}
                            disabled={loading}
                            className="group relative flex min-h-40 w-full flex-col items-center justify-center gap-3 rounded-2xl border border-[var(--border)] bg-white px-4 py-6 text-[var(--foreground)] shadow-[0_10px_26px_rgba(17,18,21,0.06)] transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-emerald-300 hover:shadow-[0_14px_34px_rgba(16,185,129,0.12)] active:translate-y-0"
                        >
                            <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-emerald-100 to-teal-100 text-emerald-600 shadow-inner transition-transform duration-200 group-hover:scale-105">
                                <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                                    <path d="M9 12l2 2 4-4" />
                                </svg>
                            </div>
                            <div className="text-center">
                                <span className="block text-sm font-semibold text-[var(--foreground)]">{t('viralVerifyFacts')}</span>
                                <div className="flex items-center justify-center gap-1.5 opacity-80 mt-1">
                                    <TokenIcon className="w-3.5 h-3.5" />
                                    <span className="text-xs font-semibold text-[var(--muted)]">
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
                            className="group relative flex min-h-40 w-full flex-col items-center justify-center gap-3 rounded-2xl border border-[var(--border)] bg-white px-4 py-6 text-[var(--foreground)] shadow-[0_10px_26px_rgba(17,18,21,0.06)] transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-purple-300 hover:shadow-[0_14px_34px_rgba(147,51,234,0.12)] active:translate-y-0"
                        >
                            <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-purple-100 to-pink-100 text-purple-600 shadow-inner transition-transform duration-200 group-hover:scale-105">
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
                                <span className="block text-sm font-semibold text-[var(--foreground)]">{t('viralGenerateMetadata')}</span>
                                <div className="flex items-center justify-center gap-1.5 opacity-80 mt-1">
                                    <TokenIcon className="w-3.5 h-3.5" />
                                    <span className="text-xs font-semibold text-[var(--muted)]">
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
                <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-center text-sm font-medium text-red-700">
                    {error}
                </div>
            )}

            {loading && (
                <div className="flex flex-col items-center justify-center space-y-4 rounded-2xl border border-[var(--border)] bg-white py-16 shadow-[0_12px_30px_rgba(17,18,21,0.06)]">
                    <div className="relative">
                        <div className="h-12 w-12 animate-spin rounded-full border-2 border-slate-200 border-t-[var(--accent)]" />
                        <div className="absolute inset-0 flex items-center justify-center">
                            <svg className="h-4 w-4 text-[var(--accent)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                            </svg>
                        </div>
                    </div>
                    <p className="animate-pulse text-sm font-medium tracking-wide text-[var(--muted)]">
                        {checkingFacts ? t('checkingFacts') : t('viralAnalyzing')}
                    </p>
                </div>
            )}

            {/* Fact Check Results */}
            {factCheckResult && (
                <div className="space-y-5 animate-fade-in">
                    {/* Header */}
                    <div className="flex items-center justify-between px-2">
                        <h4 className="flex items-center gap-2 pl-2 text-xs font-semibold uppercase tracking-widest text-[var(--muted)]">
                            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                            {t('factReport')}
                        </h4>
                        <button onClick={() => setFactCheckResult(null)} className="min-h-11 rounded-full border border-[var(--border)] bg-white px-4 text-xs font-semibold text-[var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--foreground)]">{t('closeLabel')}</button>
                    </div>

                    {/* Truth Score Card */}
                    <div className="rounded-2xl border border-[var(--border)] bg-gradient-to-br from-white to-slate-50 p-6 shadow-[0_12px_30px_rgba(17,18,21,0.07)]">
                        <div className="flex items-center justify-between gap-6">
                            {/* Score Circle */}
                            <div className="relative">
                                <svg className="w-24 h-24 -rotate-90" viewBox="0 0 100 100">
                                    <circle cx="50" cy="50" r="42" fill="none" stroke="#e5e7eb" strokeWidth="8" />
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
                                    <span className="text-2xl font-bold text-[var(--foreground)]">{factCheckResult.truth_score}</span>
                                    <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{t('scoreLabel')}</span>
                                </div>
                            </div>

                            {/* Stats */}
                            <div className="flex-1 grid grid-cols-2 gap-4">
                                <div className="rounded-2xl border border-[var(--border)] bg-white p-4">
                                    <div className="text-2xl font-bold text-[var(--foreground)]">{factCheckResult.claims_checked}</div>
                                    <div className="mt-1 text-[10px] uppercase tracking-wide text-[var(--muted)]">{t('claimsCheckedLabel')}</div>
                                </div>
                                <div className="rounded-2xl border border-[var(--border)] bg-white p-4">
                                    <div className="text-2xl font-bold text-emerald-600">{factCheckResult.supported_claims_pct}%</div>
                                    <div className="mt-1 text-[10px] uppercase tracking-wide text-[var(--muted)]">{t('supportedLabel')}</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {factCheckResult.items.length === 0 ? (
                        <div className="flex flex-col items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-6 text-center text-sm font-medium text-emerald-800 shadow-sm">
                            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5" /></svg>
                            </div>
                            <span className="text-base">{t('allVerified')}</span>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {factCheckResult.items.map((item, i) => (
                                <div key={i} className="overflow-hidden rounded-2xl border border-[var(--border)] bg-white shadow-sm transition-shadow duration-200 hover:shadow-md">
                                    {/* Item Header */}
                                    <div className="p-5 space-y-4">
                                        {/* Severity & Confidence Row */}
                                        <div className="flex items-center gap-3">
                                            <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide ${item.severity === 'major' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                                                item.severity === 'medium' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
                                                    'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                                                }`}>
                                                {t(item.severity)}
                                            </span>
                                            <div className="flex items-center gap-1.5 text-[var(--muted)]">
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
                                                <p className="text-[15px] leading-relaxed text-[var(--foreground)]">&quot;{locale === 'el' ? item.mistake_el : item.mistake_en}&quot;</p>
                                            </div>
                                        </div>

                                        {/* Correction */}
                                        <div className="pl-12">
                                            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                                                <div className="text-[10px] font-medium text-emerald-400 mb-1 uppercase tracking-wide">{t('correctionLabel')}</div>
                                                <p className="text-[15px] font-medium leading-relaxed text-[var(--foreground)]">{locale === 'el' ? item.correction_el : item.correction_en}</p>
                                                <p className="mt-3 border-t border-emerald-200 pt-3 text-xs leading-relaxed text-[var(--muted)]">{locale === 'el' ? item.explanation_el : item.explanation_en}</p>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Evidence Section */}
                                    {(item.real_life_example_el || item.real_life_example_en || item.scientific_evidence_el || item.scientific_evidence_en) && (
                                        <div className="px-5 pb-5 pt-0 space-y-3">
                                            {/* Real-life Example */}
                                            {(locale === 'el' ? item.real_life_example_el : item.real_life_example_en) && (
                                                    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                                                    <div className="flex items-center gap-2 mb-2">
                                                        <span className="text-lg">💡</span>
                                                        <span className="text-[10px] font-medium text-amber-400 uppercase tracking-wide">{t('realWorldExampleLabel')}</span>
                                                    </div>
                                                    <p className="text-sm leading-relaxed text-[var(--foreground)]">{locale === 'el' ? item.real_life_example_el : item.real_life_example_en}</p>
                                                </div>
                                            )}

                                            {/* Scientific Evidence */}
                                            {(locale === 'el' ? item.scientific_evidence_el : item.scientific_evidence_en) && (
                                                    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                                                    <div className="flex items-center gap-2 mb-2">
                                                        <span className="text-lg">🔬</span>
                                                        <span className="text-[10px] font-medium text-blue-400 uppercase tracking-wide">{t('scientificEvidenceLabel')}</span>
                                                    </div>
                                                    <p className="text-sm leading-relaxed text-[var(--foreground)]">{locale === 'el' ? item.scientific_evidence_el : item.scientific_evidence_en}</p>
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
                        <h4 className="flex items-center gap-2 pl-2 text-xs font-semibold uppercase tracking-widest text-[var(--muted)]">
                            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 4V2" /><path d="M15 16v-2" /></svg>
                            {t('metadataLabel')}
                        </h4>
                        <button onClick={() => setSocialCopyResult(null)} className="min-h-11 rounded-full border border-[var(--border)] bg-white px-4 text-xs font-semibold text-[var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--foreground)]">{t('closeLabel')}</button>
                    </div>

                    <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-white p-5 shadow-sm">
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-xs font-medium text-purple-400 uppercase tracking-wide">{t('titleLabel')}</label>
                                <CopyButton text={locale === 'el' ? socialCopyResult.social_copy.title_el : socialCopyResult.social_copy.title_en} label={t('titleLabel')} />
                            </div>
                            <div className="rounded-xl border border-[var(--border)] bg-slate-50 p-3 text-sm font-medium text-[var(--foreground)]">
                                {locale === 'el' ? socialCopyResult.social_copy.title_el : socialCopyResult.social_copy.title_en}
                            </div>
                        </div>
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-xs font-medium text-purple-400 uppercase tracking-wide">{t('descriptionLabel')}</label>
                                <CopyButton text={locale === 'el' ? socialCopyResult.social_copy.description_el : socialCopyResult.social_copy.description_en} label={t('descriptionLabel')} />
                            </div>
                            <div className="whitespace-pre-wrap rounded-xl border border-[var(--border)] bg-slate-50 p-3 text-sm leading-relaxed text-[var(--foreground)]">
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
                                    <span key={i} className="rounded-lg border border-purple-200 bg-purple-50 px-2 py-1 text-xs text-purple-700">
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
