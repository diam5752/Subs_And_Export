'use client';

import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react';
import { api } from '@/lib/api';

export interface User {
    id: string;
    email: string;
    name: string;
    provider: string;
    avatar_url?: string | null;
}

interface AuthContextType {
    user: User | null;
    isLoading: boolean;
    login: (email: string, password: string) => Promise<void>;
    register: (email: string, password: string, name: string) => Promise<void>;
    googleLogin: (idToken: string) => Promise<void>;
    logout: () => Promise<void>;
    refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

function hasStoredAuthToken(): boolean {
    if (typeof window === 'undefined') {
        return false;
    }
    return Boolean(localStorage.getItem('auth_token'));
}

function isDefinitiveSessionRejection(error: unknown): boolean {
    return typeof error === 'object'
        && error !== null
        && 'status' in error
        && error.status === 401;
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    const clearRejectedSession = useCallback(async (): Promise<boolean> => {
        try {
            // A rejected bearer can coexist with the path-scoped HttpOnly
            // media cookie. Revoke that exact cookie session before presenting
            // the browser as signed out.
            await api.revokeSession();
        } catch {
            return false;
        }
        api.clearToken();
        setUser(null);
        return true;
    }, []);

    const refreshUser = useCallback(async () => {
        if (!hasStoredAuthToken()) {
            setUser(null);
            return;
        }
        try {
            const userData = await api.getCurrentUser();
            setUser(userData);
        } catch (error) {
            if (isDefinitiveSessionRejection(error)) {
                await clearRejectedSession();
            }
        }
    }, [clearRejectedSession]);

    useEffect(() => {
        // Check for existing session
        const checkAuth = async () => {
            if (!hasStoredAuthToken()) {
                setUser(null);
                setIsLoading(false);
                return;
            }
            try {
                const userData = await api.getCurrentUser();
                setUser(userData);
                setIsLoading(false);
            } catch (error) {
                if (!isDefinitiveSessionRejection(error)) {
                    // Authentication is unknown while the API is temporarily
                    // unavailable. Keep the guarded loading state and stored
                    // bearer instead of falsely rendering a signed-out UI.
                    return;
                }
                if (await clearRejectedSession()) {
                    setIsLoading(false);
                }
            }
        };
        checkAuth();
    }, [clearRejectedSession]);

    const login = useCallback(async (email: string, password: string) => {
        await api.login(email, password);
        await refreshUser();
    }, [refreshUser]);

    const register = useCallback(async (email: string, password: string, name: string) => {
        await api.register(email, password, name);
        await login(email, password);
    }, [login]);

    const googleLogin = useCallback(async (idToken: string) => {
        await api.googleLogin(idToken);
        await refreshUser();
    }, [refreshUser]);

    const logout = useCallback(async () => {
        // The HttpOnly private-media cookie cannot be cleared by JavaScript.
        // Keep the browser visibly signed in until the server has revoked the
        // session and returned the cookie-expiry header.
        await api.revokeSession();
        api.clearToken();
        setUser(null);
    }, []);

    return (
        <AuthContext.Provider value={{ user, isLoading, login, register, googleLogin, logout, refreshUser }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
}
