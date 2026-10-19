import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

declare const process: { env: Record<string, string | undefined> };

// The launcher (start-studio.bat / start-studio.sh dev) sets STUDIO_API_URL when the backend is not on port 8000.
const apiTarget = process.env.STUDIO_API_URL || "http://127.0.0.1:8000";

// The production build is written into the Python package (app/web) and served by FastAPI,
// so the studio runs without Node.js. During development, `npm run dev` proxies /api to uvicorn.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../app/web",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": apiTarget },
  },
});
