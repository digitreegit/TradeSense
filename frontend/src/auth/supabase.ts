import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

if (!url || !anonKey) {
  // Keep explicit to avoid silent auth failures.
  // eslint-disable-next-line no-console
  console.warn(
    'Supabase env is missing. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.',
  );
}

export const supabase = createClient(url ?? '', anonKey ?? '');
