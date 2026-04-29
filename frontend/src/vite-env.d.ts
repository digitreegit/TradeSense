/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public API prefix, e.g. `/quant/api` when the app is hosted under `/quant/` */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
