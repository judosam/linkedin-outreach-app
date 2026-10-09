import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

/* Builds straight into the FastAPI-served static tree at `static/dist`.
   Fixed asset names (app.js / app.css) let `templates/index.html` reference
   the bundle directly; FastAPI stamps `?v=<mtime>-<size>` on every /static
   asset at request time, so caching stays correct without content hashes. */
export default defineConfig({
  base: '/static/dist/',
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'app.js',
        chunkFileNames: '[name].js',
        assetFileNames: (info) =>
          info.name && info.name.endsWith('.css') ? 'app.css' : 'assets/[name][extname]',
      },
    },
  },
});
