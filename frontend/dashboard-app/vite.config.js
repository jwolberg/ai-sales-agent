import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Served by FastAPI under /dashboard/ (StaticFiles mount). Dev server proxies the API to the
// backend on :8000 so `npm run dev` works against a local uvicorn.
export default defineConfig({
  plugins: [react()],
  base: '/dashboard/',
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
