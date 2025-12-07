import el from '@/i18n/el.json';
import en from '@/i18n/en.json';

export type Locale = 'el' | 'en';

export type Messages = typeof en;

export const defaultLocale: Locale = 'el';

export const messages: Record<Locale, Messages> = { el, en } as const;

export const locales: Locale[] = Object.keys(messages) as Locale[];
