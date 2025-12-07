'use client';

import { useMemo } from 'react';
import { useI18n } from '@/context/I18nContext';
import { messages } from '@/context/i18nMessages';

export function LanguageToggle() {
  const { locale, setLocale, t } = useI18n();

  const nextLocale = useMemo(() => (locale === 'el' ? 'en' : 'el'), [locale]);

  return (
    <button
      type="button"
      onClick={() => setLocale(nextLocale)}
      className="flex items-center gap-2 rounded-full bg-white/10 border border-[var(--border)] px-3 py-2 text-sm shadow-lg hover:bg-white/15 transition-colors"
      aria-label={`${t('languageToggleLabel')}: ${messages[nextLocale].languageNameEn}`}
    >
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">
        {t('languageToggleLabel')}
      </span>
      <span className="font-semibold">
        {nextLocale === 'el' ? 'ΕΛ' : 'EN'}
      </span>
    </button>
  );
}
