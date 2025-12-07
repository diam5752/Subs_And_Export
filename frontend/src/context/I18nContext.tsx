'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { defaultLocale, locales, messages, Locale, Messages } from './i18nMessages';

type MessageKey = keyof Messages;

interface I18nContextType {
  locale: Locale;
  setLocale: (nextLocale: Locale) => void;
  t: (key: MessageKey) => string;
  availableLocales: Locale[];
}

const I18N_STORAGE_KEY = 'preferredLocale';
const I18nContext = createContext<I18nContextType | null>(null);

export function I18nProvider({ children, initialLocale }: { children: React.ReactNode; initialLocale?: Locale }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    if (initialLocale && locales.includes(initialLocale)) {
      return initialLocale;
    }

    const storedLocale = typeof window !== 'undefined' ? localStorage.getItem(I18N_STORAGE_KEY) : null;
    if (storedLocale && locales.includes(storedLocale as Locale)) {
      return storedLocale as Locale;
    }
    return defaultLocale;
  });

  useEffect(() => {
    if (typeof document === 'undefined') return;
    document.documentElement.lang = locale;
    if (typeof window !== 'undefined') {
      localStorage.setItem(I18N_STORAGE_KEY, locale);
    }
  }, [locale]);

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
  }, []);

  const t = useCallback(
    (key: MessageKey) => {
      return messages[locale][key] ?? messages[defaultLocale][key] ?? key;
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
