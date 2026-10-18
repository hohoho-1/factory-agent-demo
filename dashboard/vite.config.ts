import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발 서버에서 /api 를 Spring Boot(8080)로 넘긴다 → CORS 설정 없이 SSE 포함 그대로 동작
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
    },
  },
})
