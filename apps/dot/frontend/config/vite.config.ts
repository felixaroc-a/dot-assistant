import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const configDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(configDir, '..')

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  root: repoRoot,
  plugins: [react()],
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(repoRoot, 'src'),
    },
  },
  build: {
    sourcemap: false,
    minify: 'esbuild',
    reportCompressedSize: true,
    cssMinify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-motion': ['framer-motion'],
          'vendor-state': ['zustand'],
        },
      },
    },
  },
  esbuild: {
    drop: mode === 'production' ? ['console', 'debugger'] : [],
    legalComments: 'none',
  },
}))
