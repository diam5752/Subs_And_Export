'use client';

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, type PointsBalanceResponse } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

interface PointsContextValue {
    balance: number | null;
    paidBalance: number | null;
    promotionalBalance: number | null;
    reversalDebt: number | null;
    aiSpendableBalance: number | null;
    isLoading: boolean;
    error: string | null;
    refreshBalance: () => Promise<void>;
    setBalance: (balance: number | null) => void;
    setWallet: (wallet: PointsBalanceResponse) => void;
}

const PointsContext = createContext<PointsContextValue | null>(null);

export function PointsProvider({ children }: { children: React.ReactNode }) {
    const { user, isLoading: authLoading } = useAuth();
    const isAuthenticated = !authLoading && Boolean(user);
    const sessionKey = authLoading ? 'auth-loading' : user ? `user:${user.id}` : 'guest';

    return (
        <PointsSession sessionKey={sessionKey} isAuthenticated={isAuthenticated}>
            {children}
        </PointsSession>
    );
}

interface PointsState {
    sessionKey: string;
    balance: number | null;
    paidBalance: number | null;
    promotionalBalance: number | null;
    reversalDebt: number | null;
    aiSpendableBalance: number | null;
    isLoading: boolean;
    error: string | null;
}

function createPointsState(sessionKey: string, isAuthenticated: boolean): PointsState {
    return {
        sessionKey,
        balance: null,
        paidBalance: null,
        promotionalBalance: null,
        reversalDebt: null,
        aiSpendableBalance: null,
        isLoading: isAuthenticated,
        error: null,
    };
}

function walletState(
    result: Partial<PointsBalanceResponse> & Pick<PointsBalanceResponse, 'balance'>,
): Pick<
    PointsState,
    'balance' | 'paidBalance' | 'promotionalBalance' | 'reversalDebt' | 'aiSpendableBalance'
> {
    const paidBalance = result.paid_balance ?? 0;
    const reversalDebt = result.reversal_debt ?? 0;
    return {
        balance: result.balance,
        paidBalance,
        promotionalBalance: result.promotional_balance ?? Math.max(0, result.balance - paidBalance),
        reversalDebt,
        aiSpendableBalance: result.ai_spendable_balance ?? (reversalDebt > 0 ? 0 : paidBalance),
    };
}

function PointsSession({
    children,
    sessionKey,
    isAuthenticated,
}: {
    children: React.ReactNode;
    sessionKey: string;
    isAuthenticated: boolean;
}) {
    const [state, setState] = useState<PointsState>(() => createPointsState(sessionKey, isAuthenticated));

    // Reset only the balance session. Keying the provider itself would remount
    // the entire application and discard a guest's selected video at login.
    if (state.sessionKey !== sessionKey) {
        setState(createPointsState(sessionKey, isAuthenticated));
    }

    const setBalance = useCallback((balance: number | null) => {
        setState((current) => current.sessionKey === sessionKey
            ? { ...current, balance }
            : current);
    }, [sessionKey]);

    const setWallet = useCallback((wallet: PointsBalanceResponse) => {
        setState((current) => current.sessionKey === sessionKey
            ? { ...current, ...walletState(wallet) }
            : current);
    }, [sessionKey]);

    const refreshBalance = useCallback(async () => {
        if (!isAuthenticated) return;

        const requestSession = sessionKey;
        setState((current) => current.sessionKey === requestSession
            ? { ...current, isLoading: true, error: null }
            : current);
        try {
            const result = await api.getPointsBalance();
            setState((current) => current.sessionKey === requestSession
                ? { ...current, ...walletState(result) }
                : current);
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to load balance';
            setState((current) => current.sessionKey === requestSession
                ? { ...current, error: message }
                : current);
        } finally {
            setState((current) => current.sessionKey === requestSession
                ? { ...current, isLoading: false }
                : current);
        }
    }, [isAuthenticated, sessionKey]);

    useEffect(() => {
        if (!isAuthenticated) return;

        let active = true;
        const requestSession = sessionKey;
        api.getPointsBalance()
            .then((result) => {
                if (active) {
                    setState((current) => current.sessionKey === requestSession
                        ? { ...current, ...walletState(result) }
                        : current);
                }
            })
            .catch((err: unknown) => {
                if (active) {
                    const message = err instanceof Error ? err.message : 'Failed to load balance';
                    setState((current) => current.sessionKey === requestSession
                        ? { ...current, error: message }
                        : current);
                }
            })
            .finally(() => {
                if (active) {
                    setState((current) => current.sessionKey === requestSession
                        ? { ...current, isLoading: false }
                        : current);
                }
            });

        return () => {
            active = false;
        };
    }, [isAuthenticated, sessionKey]);

    const value = useMemo<PointsContextValue>(() => ({
        balance: state.balance,
        paidBalance: state.paidBalance,
        promotionalBalance: state.promotionalBalance,
        reversalDebt: state.reversalDebt,
        aiSpendableBalance: state.aiSpendableBalance,
        isLoading: state.isLoading,
        error: state.error,
        refreshBalance,
        setBalance,
        setWallet,
    }), [
        refreshBalance,
        setBalance,
        setWallet,
        state.aiSpendableBalance,
        state.balance,
        state.error,
        state.isLoading,
        state.paidBalance,
        state.promotionalBalance,
        state.reversalDebt,
    ]);

    return <PointsContext.Provider value={value}>{children}</PointsContext.Provider>;
}

export function usePoints(): PointsContextValue {
    const context = useContext(PointsContext);
    if (!context) {
        throw new Error('usePoints must be used within a PointsProvider');
    }
    return context;
}
