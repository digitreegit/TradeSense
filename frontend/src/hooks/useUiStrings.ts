import { useAppStore } from '../stores/useAppStore';
import { getUiStrings } from '../locale/uiStrings';

export function useUiStrings() {
  const appLocale = useAppStore((s) => s.appLocale);
  return getUiStrings(appLocale);
}
