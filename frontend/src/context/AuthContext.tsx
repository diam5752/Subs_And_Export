"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
  useCallback,
} from "react";
import { api } from "@/lib/api";

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
  sessionUnavailable: boolean;
  betaCreditsAwarded: number;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  googleLogin: (idToken: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  retrySession: () => Promise<void>;
  dismissBetaCreditsAwarded: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

function hasStoredAuthToken(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return Boolean(localStorage.getItem("auth_token"));
}

function isDefinitiveSessionRejection(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    error.status === 401
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [sessionUnavailable, setSessionUnavailable] = useState(false);
  const [betaCreditsAwarded, setBetaCreditsAwarded] = useState(0);

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
    setBetaCreditsAwarded(0);
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

  const retrySession = useCallback(async () => {
    setIsLoading(true);
    setSessionUnavailable(false);

    if (!hasStoredAuthToken()) {
      setUser(null);
      setIsLoading(false);
      return;
    }

    try {
      const userData = await api.getCurrentUser();
      setUser(userData);
    } catch (error) {
      if (isDefinitiveSessionRejection(error)) {
        const cleared = await clearRejectedSession();
        if (!cleared) {
          setSessionUnavailable(true);
        }
      } else {
        // Preserve the bearer and avoid falsely rendering a signed-out
        // session. The app now exposes an explicit retry surface rather
        // than retaining an unbounded full-screen loading state.
        setSessionUnavailable(true);
      }
    } finally {
      setIsLoading(false);
    }
  }, [clearRejectedSession]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void retrySession();
    });
    return () => {
      active = false;
    };
  }, [retrySession]);

  const login = useCallback(
    async (email: string, password: string) => {
      const response = await api.login(email, password);
      setBetaCreditsAwarded(response.beta_credits_awarded ?? 0);
      await refreshUser();
    },
    [refreshUser],
  );

  const register = useCallback(
    async (email: string, password: string, name: string) => {
      await api.register(email, password, name);
      await login(email, password);
    },
    [login],
  );

  const googleLogin = useCallback(
    async (idToken: string) => {
      const response = await api.googleLogin(idToken);
      setBetaCreditsAwarded(response.beta_credits_awarded ?? 0);
      await refreshUser();
    },
    [refreshUser],
  );

  const logout = useCallback(async () => {
    // The HttpOnly private-media cookie cannot be cleared by JavaScript.
    // Keep the browser visibly signed in until the server has revoked the
    // session and returned the cookie-expiry header.
    await api.revokeSession();
    api.clearToken();
    setUser(null);
    setBetaCreditsAwarded(0);
  }, []);

  const dismissBetaCreditsAwarded = useCallback(() => {
    setBetaCreditsAwarded(0);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        sessionUnavailable,
        betaCreditsAwarded,
        login,
        register,
        googleLogin,
        logout,
        refreshUser,
        retrySession,
        dismissBetaCreditsAwarded,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
