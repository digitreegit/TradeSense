import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'

/** Repo root — same `.env` search tree as FastAPI (`backend/app/core/config.py`). */
const repoRoot = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // One repo-root `.env` can hold `SUPABASE_*` (backend) and `VITE_*` (browser bundle).
  envDir: repoRoot,
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
}))
