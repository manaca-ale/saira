import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Keep the frontend using a relative API base (/api/...) while developing locally.
    // This avoids CORS and avoids hardcoding backend ports in the app code.
    proxy: {
      "/api": {
        // Override with VITE_PROXY_API_TARGET when the local backend is on
        // another port (e.g. the saira-test stack maps it to 8002).
        target: process.env.VITE_PROXY_API_TARGET || "http://localhost:8001",
        changeOrigin: true,
      },
      "/uploads": {
        target: "http://localhost:5002",
        changeOrigin: true,
      },
      "/s3-images": {
        target: "https://saira-images.s3.sa-east-1.amazonaws.com",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/s3-images/, ""),
        secure: true,
      },
    },
  },
});
