import type { AppLocale } from '../stores/types';

export const LOCALE_STORAGE_KEY = 'tradesense-locale';

export function readStoredLocale(): AppLocale {
  try {
    const v = localStorage.getItem(LOCALE_STORAGE_KEY);
    if (v === 'en' || v === 'ko') return v;
  } catch {
    /* private mode */
  }
  return 'en';
}

export function persistLocale(locale: AppLocale): void {
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    /* ignore */
  }
}

export function applyLocaleToDocument(locale: AppLocale): void {
  document.documentElement.lang = locale === 'ko' ? 'ko' : 'en';
}
