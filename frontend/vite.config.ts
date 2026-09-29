import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

const apiTarget = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      // ws: true is required so the /api/ws/* channels survive the dev proxy
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
      '/static': { target: apiTarget, changeOrigin: true },
      '/health': { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  // lets `npm run preview` exercise the production bundle against the API
  preview: {
    host: true,
    port: 4173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
      '/static': { target: apiTarget, changeOrigin: true },
      '/health': { target: apiTarget, changeOrigin: true },
    },
  },
})
