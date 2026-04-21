const KEY = 'tradesense_token';
const LAST_AUTH_METHOD_KEY = 'tradesense_last_auth_method';
export type AuthMethod = 'google' | 'email';

export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  localStorage.setItem(KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(KEY);
}

export function setLastAuthMethod(method: AuthMethod): void {
  localStorage.setItem(LAST_AUTH_METHOD_KEY, method);
}

export function getLastAuthMethod(): AuthMethod | null {
  const v = localStorage.getItem(LAST_AUTH_METHOD_KEY);
  return v === 'google' || v === 'email' ? v : null;
}
