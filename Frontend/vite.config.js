import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const backendTarget = process.env.VITE_API_TARGET || process.env.BACKEND_URL || 'https://soultune-zctz.onrender.com';
const isExternal = !backendTarget.includes('127.0.0.1') && !backendTarget.includes('localhost');

const proxyConfig = {
  target: backendTarget,
  changeOrigin: isExternal,
  configure: (proxy) => {
    proxy.on('error', (err, req, res) => {
      if (!res.headersSent) {
        res.writeHead(503, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ detail: `Backend server is unreachable. Target: ${backendTarget}` }));
      }
    });
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true, proxy: { '/api': proxyConfig } },
  preview: { port: 4173, strictPort: true, proxy: { '/api': proxyConfig } },
});
