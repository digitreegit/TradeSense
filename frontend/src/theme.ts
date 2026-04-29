export type ColorMode = 'light' | 'dark';

const STORAGE_KEY = 'tradesense-color-mode';

export function readStoredColorMode(): ColorMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'light' || v === 'dark') return v;
  } catch {
    /* ignore */
  }
  if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: light)').matches) {
    return 'light';
  }
  return 'dark';
}

export function applyColorMode(mode: ColorMode): void {
  document.documentElement.dataset.colorMode = mode;
  document.documentElement.style.colorScheme = mode === 'light' ? 'light' : 'dark';
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}
