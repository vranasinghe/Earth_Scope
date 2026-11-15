import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Unit/component tests only; the dev server and build keep using vite.config.ts.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
