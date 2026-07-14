import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'

const frontendDir = fileURLToPath(new URL('.', import.meta.url))
/** Same tree FastAPI uses for root `.env` (`backend/app/core/config.py`). */
const repoRoot = fileURLToPath(new URL('..', import.meta.url))

/** Merge `VITE_*` from repo root + `frontend/` `.env*`, then overlay `process.env` (Docker build `ARG`/`ENV`). */
function vitePublicEnv(mode: string) {
  const fromFiles = { ...loadEnv(mode, repoRoot, 'VITE_'), ...loadEnv(mode, frontendDir, 'VITE_') }
  const fromProcess: Record<string, string> = {}
  for (const [k, v] of Object.entries(process.env)) {
    if (k.startsWith('VITE_') && typeof v === 'string' && v.length > 0) {
      fromProcess[k] = v
    }
  }
  return { ...fromFiles, ...fromProcess }
}

export default defineConfig(({ mode }) => {
  const viteEnv = vitePublicEnv(mode)
  const defineEnv = Object.fromEntries(
    Object.entries(viteEnv).map(([key, val]) => [`import.meta.env.${key}`, JSON.stringify(val)]),
  )

  /** Root deploy (Docker EC2 :8000): set VITE_PUBLIC_BASE=/ in env. Legacy cPanel: /quant/ */
  const publicBaseRaw =
    typeof viteEnv.VITE_PUBLIC_BASE === 'string' && viteEnv.VITE_PUBLIC_BASE.trim().length > 0
      ? viteEnv.VITE_PUBLIC_BASE.trim()
      : mode === 'production'
        ? '/quant/'
        : '/'
  const productionBase = publicBaseRaw.endsWith('/') ? publicBaseRaw : `${publicBaseRaw}/`

  return {
    plugins: [react()],
    // `.env*` under `frontend/`; `define` also injects `VITE_*` from repo root (either file works).
    envDir: frontendDir,
    define: defineEnv,
    base: mode === 'production' ? productionBase : '/',
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5173,
      host: '127.0.0.1',
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
        '/ws': {
          target: 'ws://localhost:8000',
          ws: true,
        },
      },
    },
  }
})
