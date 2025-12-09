import { useState, useCallback, useEffect } from 'react';
import { api, HistoryEvent } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';

export function useHistory() {
    const { user } = useAuth();
    const { t } = useI18n();

    const [historyItems, setHistoryItems] = useState<HistoryEvent[]>([]);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyError, setHistoryError] = useState('');

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

    // Initial load
    useEffect(() => {
        if (user) {
            loadHistory();
        }
    }, [user, loadHistory]);

    return {
        historyItems,
        historyLoading,
        historyError,
        loadHistory,
    };
}
