'use client';

import { useMemo } from 'react';
import { useI18n } from '@/context/I18nContext';

export function LanguageToggle() {
  const { locale, setLocale, t } = useI18n();

  const nextLocale = useMemo(() => (locale === 'el' ? 'en' : 'el'), [locale]);

  return (
    <button
      type="button"
      onClick={() => setLocale(nextLocale)}
      className="flex items-center gap-1.5 rounded-full bg-white/5 border border-[var(--border)] px-2.5 py-1.5 text-sm hover:bg-white/10 transition-all duration-200"
      aria-label={t('switchLanguage', { language: nextLocale === 'el' ? t('languageNameEl') : t('languageNameEn') })}
    >
      <span className="text-lg leading-none">{locale === 'el' ? '🇬🇷' : '🇬🇧'}</span>
      <span className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide">
        {locale === 'el' ? 'ΕΛ' : 'EN'}
      </span>
    </button>
  );
}
