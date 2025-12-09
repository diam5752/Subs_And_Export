import React from 'react';
import { useI18n } from '@/context/I18nContext';
import { HistoryEvent } from '@/lib/api';

interface HistoryViewProps {
    historyItems: HistoryEvent[];
    historyLoading: boolean;
    historyError: string;
    onRefresh: () => void;
    formatDate: (ts: string | number) => string;
}

export function HistoryView({
    historyItems,
    historyLoading,
    historyError,
    onRefresh,
    formatDate,
}: HistoryViewProps) {
    const { t } = useI18n();

    return (
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
                        onClick={onRefresh}
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
                    {historyItems.map((evt, idx) => (
                        // Using idx as fallback key if timestamp collision
                        <div
                            key={`${evt.ts}-${evt.kind}-${idx}`}
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
    );
}
