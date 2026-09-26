import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Every /api call is forwarded to the Python backend, so the browser talks to
// one origin and there is no CORS to configure in development.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': process.env.DS_API || 'http://localhost:8000' } },
})
