import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the Domain API and event WebSocket to the FastAPI
// server (uv run workbench-server, 127.0.0.1:8000), so no CORS is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
