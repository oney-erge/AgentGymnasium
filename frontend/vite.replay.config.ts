import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build the same trace renderer as a self-contained script for HTML exports.
export default defineConfig({
  plugins: [react()],
  publicDir: false,
  // Library mode otherwise preserves process.env.NODE_ENV for consumers; the
  // standalone HTML has no Node process and should use production React.
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: '../backend/agentgymnasium/static/replay',
    emptyOutDir: true,
    lib: {
      entry: fileURLToPath(new URL('./src/replay.tsx', import.meta.url)),
      name: 'AgentGymnasiumReplay',
      formats: ['iife'],
      fileName: () => 'replay.js',
      cssFileName: 'replay',
    },
  },
})
