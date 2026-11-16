import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": process.env.RECONFLOW_API_URL || "http://localhost:58000",
      "/health": process.env.RECONFLOW_API_URL || "http://localhost:58000",
    },
  },
});
