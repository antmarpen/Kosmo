/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The `/api` proxy target is injectable so the Vite dev server works both on
// the host (default http://localhost:8000) and inside Docker Compose, where
// API_PROXY_TARGET=http://backend:8000 is set in docker-compose.yml.
const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

const srcPath = fileURLToPath(new URL("./src", import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": srcPath,
    },
  },
  server: {
    // Listen on all interfaces so the compose healthcheck and the port
    // mapping reach the dev server inside the container.
    host: true,
    port: 5173,
    strictPort: true,
    watch: {
      // Docker Desktop bind mounts do not reliably deliver file events;
      // compose opts into polling via CHOKIDAR_USEPOLLING=true.
      usePolling: process.env.CHOKIDAR_USEPOLLING === "true",
    },
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
