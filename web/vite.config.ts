import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, Vite serves on :5173 and the API lives on :8000.
// Proxying /api through Vite keeps the frontend code identical in dev and prod:
// it always calls same-origin /api/... and never needs to know a backend URL.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
