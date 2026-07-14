export const THEME_STORAGE_KEY = 'tradesense-theme';

export type ColorTheme = 'dark' | 'light';

export function readStoredTheme(): ColorTheme {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    if (v === 'light' || v === 'dark') return v;
  } catch {
    /* private mode / SSR */
  }
  return 'dark';
}

export function persistTheme(theme: ColorTheme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* ignore */
  }
}

export function applyThemeToDocument(theme: ColorTheme): void {
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
}
