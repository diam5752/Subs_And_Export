'use client';

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

export interface PointsContextValue {
    balance: number | null;
    isLoading: boolean;
    error: string | null;
    refreshBalance: () => Promise<void>;
    setBalance: (balance: number | null) => void;
}

const PointsContext = createContext<PointsContextValue | null>(null);

export function PointsProvider({ children }: { children: React.ReactNode }) {
    const { user, isLoading: authLoading } = useAuth();
    const [balance, setBalance] = useState<number | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const refreshBalance = useCallback(async () => {
        if (!user) {
            setBalance(null);
            return;
        }

        setIsLoading(true);
        setError(null);
        try {
            const result = await api.getPointsBalance();
            setBalance(result.balance);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load balance');
        } finally {
            setIsLoading(false);
        }
    }, [user]);

    useEffect(() => {
        if (authLoading) return;
        if (!user) {
            setBalance(null);
            setError(null);
            setIsLoading(false);
            return;
        }
        void refreshBalance();
    }, [authLoading, refreshBalance, user]);

    const value = useMemo<PointsContextValue>(() => ({
        balance,
        isLoading,
        error,
        refreshBalance,
        setBalance,
    }), [balance, error, isLoading, refreshBalance]);

    return <PointsContext.Provider value={value}>{children}</PointsContext.Provider>;
}

export function usePoints(): PointsContextValue {
    const context = useContext(PointsContext);
    if (!context) {
        throw new Error('usePoints must be used within a PointsProvider');
    }
    return context;
}

