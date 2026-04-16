import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite config for EchoVessel web frontend
// - Dev: runs on :5173, proxies /api/* and /events (SSE) to the daemon's
//   FastAPI on :7777
// - Build: outputs to ../static/ for FastAPI's StaticFiles to serve
//
// The static/ tree is what gets embedded into the wheel by the hatch
// build hook (see hatch_build.py at repo root). Anything under
// ../static/ after `npm run build` completes is shipped to end users.

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:7777',
        changeOrigin: true,
      },
      '/events': {
        // Server-Sent Events endpoint. Vite's dev proxy needs this so
        // the long-lived SSE connection reaches the daemon instead of
        // being served by Vite's own 404 handler during dev.
        target: 'http://localhost:7777',
        changeOrigin: true,
      },
    },
  },
  build: {
    // Relative to the frontend/ directory. Resolves to
    // src/echovessel/channels/web/static/ which is what hatch bundles
    // into the wheel. Do not change without updating hatch_build.py +
    // pyproject.toml `[tool.hatch.build.targets.wheel.force-include]`.
    outDir: '../static',
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: false,
  },
})
