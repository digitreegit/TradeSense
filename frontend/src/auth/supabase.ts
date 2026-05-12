import { createClient, type SupabaseClient } from '@supabase/supabase-js';

const url = (import.meta.env.VITE_SUPABASE_URL as string | undefined)?.trim();
const anonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined)?.trim();

/** Google OAuth and session refresh require a real Supabase project. */
export const isSupabaseConfigured = Boolean(url && anonKey);

if (!isSupabaseConfigured) {
  // eslint-disable-next-line no-console
  console.warn(
    'Supabase env is missing. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY (build-time for Docker). Google sign-in is disabled until then.',
  );
}

/** `null` when env is missing — avoids createClient('', '') throwing at import time. */
export const supabase: SupabaseClient | null = isSupabaseConfigured
  ? createClient(url!, anonKey!)
  : null;
