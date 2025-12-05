'use client';

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
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

    const refreshUser = async () => {
        try {
            const userData = await api.getCurrentUser();
            setUser(userData);
        } catch {
            api.clearToken();
            setUser(null);
        }
    };

    useEffect(() => {
        // Check for existing session
        const checkAuth = async () => {
            try {
                const userData = await api.getCurrentUser();
                setUser(userData);
            } catch {
                // Not authenticated
                api.clearToken();
            } finally {
                setIsLoading(false);
            }
        };
        checkAuth();
    }, []);

    const login = async (email: string, password: string) => {
        await api.login(email, password);
        const userData = await api.getCurrentUser();
        setUser(userData);
    };

    const register = async (email: string, password: string, name: string) => {
        await api.register(email, password, name);
        // Automatically log in after registration
        await login(email, password);
    };

    const googleLogin = async (code: string, state: string) => {
        await api.googleCallback(code, state);
        const userData = await api.getCurrentUser();
        setUser(userData);
    };

    const logout = () => {
        api.clearToken();
        setUser(null);
    };

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
