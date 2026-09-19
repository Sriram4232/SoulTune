import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const proxyConfig = {
  target: 'http://127.0.0.1:8000',
  changeOrigin: false,
  configure: (proxy) => {
    proxy.on('error', (err, req, res) => {
      if (!res.headersSent) {
        res.writeHead(503, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ detail: 'Backend server is unreachable. Please ensure the backend is running on http://127.0.0.1:8000.' }));
      }
    });
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true, proxy: { '/api': proxyConfig } },
  preview: { port: 4173, strictPort: true, proxy: { '/api': proxyConfig } },
});
