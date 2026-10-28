import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev the API runs on the host (uvicorn :8000); in Docker nginx does the proxying.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": process.env.API_URL ?? "http://localhost:8000" } },
});
