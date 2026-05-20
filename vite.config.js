import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  root:   "electron/renderer",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "electron/renderer") },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: path.resolve(__dirname, "dist/renderer"),
    emptyOutDir: true,
  },
});
