import { defineConfig, loadEnv, type ProxyOptions } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The capture API sends no CORS headers, so the dashboard reaches it through `/api`.
const DEFAULT_API = 'https://qasim-test.35-253-10-71.sslip.io';

export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, process.cwd(), '').API_TARGET || DEFAULT_API;
  const proxy: Record<string, ProxyOptions> = {
    '/api': { target, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
  };
  return {
    plugins: [react(), tailwindcss()],
    server: { proxy },
    preview: { proxy },
  };
});
