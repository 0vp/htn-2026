import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const backend = process.env.VITE_API_PROXY_TARGET ?? 'https://qasim-test.35-253-10-71.sslip.io';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/v1': backend,
      '/health': backend,
    },
  },
});
