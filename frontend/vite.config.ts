import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // During development the frontend calls /api/* and Vite forwards the request
  // to the FastAPI backend, so no CORS setup or API keys are needed in the browser.
  const backend = env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'
  const proxy = { '/api': { target: backend, changeOrigin: true } }
  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
  }
})
