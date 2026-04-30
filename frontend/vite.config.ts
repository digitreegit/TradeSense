import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'

const frontendDir = fileURLToPath(new URL('.', import.meta.url))
/** Same tree FastAPI uses for root `.env` (`backend/app/core/config.py`). */
const repoRoot = fileURLToPath(new URL('..', import.meta.url))

/** Merge `VITE_*` from repo root and `frontend/` so either layout works (frontend wins on conflict). */
function vitePublicEnv(mode: string) {
  const fromRoot = loadEnv(mode, repoRoot, 'VITE_')
  const fromFrontend = loadEnv(mode, frontendDir, 'VITE_')
  return { ...fromRoot, ...fromFrontend }
}

export default defineConfig(({ mode }) => {
  const viteEnv = vitePublicEnv(mode)
  const defineEnv = Object.fromEntries(
    Object.entries(viteEnv).map(([key, val]) => [`import.meta.env.${key}`, JSON.stringify(val)]),
  )

  return {
    plugins: [react()],
    // `.env*` under `frontend/`; `define` also injects `VITE_*` from repo root (either file works).
    envDir: frontendDir,
    define: defineEnv,
    base: mode === 'production' ? '/quant/' : '/',
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
