'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { defaultLocale, locales, messages, Locale, Messages } from './i18nMessages';

type MessageKey = keyof Messages;

interface I18nContextType {
  locale: Locale;
  setLocale: (nextLocale: Locale) => void;
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
  availableLocales: Locale[];
}

const I18N_STORAGE_KEY = 'preferredLocale';
const I18nContext = createContext<I18nContextType | null>(null);

// Get stored locale - only call on client
function getStoredLocale(): Locale | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(I18N_STORAGE_KEY);
  if (stored && locales.includes(stored as Locale)) {
    return stored as Locale;
  }
  return null;
}

export function I18nProvider({ children, initialLocale }: { children: React.ReactNode; initialLocale?: Locale }) {
  // Always initialize with defaultLocale (or initialLocale prop) for SSR consistency.
  // This ensures server and client first-render produce identical output.
  const [locale, setLocaleState] = useState<Locale>(
    initialLocale && locales.includes(initialLocale) ? initialLocale : defaultLocale
  );
  const [isHydrated, setIsHydrated] = useState(false);

  // After hydration, sync locale FROM localStorage (if different from default)
  useEffect(() => {
    const stored = getStoredLocale();
    if (stored && stored !== locale) {
      setLocaleState(stored);
    }
    setIsHydrated(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run once on mount

  // Sync TO external systems (document.lang, localStorage) after hydration
  useEffect(() => {
    if (!isHydrated) return; // Skip during initial hydration
    if (typeof document !== 'undefined') {
      document.documentElement.lang = locale;
    }
    if (typeof window !== 'undefined') {
      localStorage.setItem(I18N_STORAGE_KEY, locale);
    }
  }, [locale, isHydrated]);

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
  }, []);

  const t = useCallback(
    (key: MessageKey, params?: Record<string, string | number>) => {
      let message = (messages[locale][key] ?? messages[defaultLocale][key] ?? key) as string;
      if (params) {
        Object.entries(params).forEach(([k, v]) => {
          message = message.replace(`{${k}}`, String(v));
        });
      }
      return message;
    },
    [locale],
  );

  const value = useMemo(
    () => ({
      locale,
      setLocale,
      t,
      availableLocales: locales,
    }),
    [locale, setLocale, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error('useI18n must be used within an I18nProvider');
  }
  return context;
}
