'use client';

import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react';
import { api } from '@/lib/api';

interface User {
    id: string;
    email: string;
    name: string;
    provider: string;
}

interface AuthContextType {
    user: User | null;
    isLoading: boolean;
    login: (email: string, password: string) => Promise<void>;
    register: (email: string, password: string, name: string) => Promise<void>;
    googleLogin: (code: string, state: string) => Promise<void>;
    logout: () => void;
    refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    const refreshUser = useCallback(async () => {
        try {
            const userData = await api.getCurrentUser();
            setUser(userData);
        } catch {
            api.clearToken();
            setUser(null);
        }
    }, []);

    useEffect(() => {
        // Check for existing session
        const checkAuth = async () => {
            try {
                const userData = await api.getCurrentUser();
                setUser(userData);
            } catch {
                api.clearToken();
            } finally {
                setIsLoading(false);
            }
        };
        checkAuth();
    }, []);

    const login = useCallback(async (email: string, password: string) => {
        await api.login(email, password);
        await refreshUser();
    }, [refreshUser]);

    const register = useCallback(async (email: string, password: string, name: string) => {
        await api.register(email, password, name);
        await login(email, password);
    }, [login]);

    const googleLogin = useCallback(async (code: string, state: string) => {
        await api.googleCallback(code, state);
        await refreshUser();
    }, [refreshUser]);

    const logout = useCallback(() => {
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
