import { defineConfig } from "vite";

// In dev, API and websocket calls go to the Python server on 8000.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
});
