/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public API prefix, e.g. `/quant/api` when the app is hosted under `/quant/` */
  readonly VITE_API_BASE?: string;
  /** Vite `base` in production, e.g. `/` for Docker on :8000 or `/quant/` for cPanel subpath */
  readonly VITE_PUBLIC_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
