import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const vercel = process.env.VERCEL === "1" || process.env.VITE_BASE === "/";

export default defineConfig({
  plugins: [react()],
  base: vercel ? "/" : "/app/",
  build: {
    outDir: process.env.ARI_DESKTOP_OUT_DIR || process.env.KYN_DESKTOP_OUT_DIR || "../web/dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/hooks": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
});
