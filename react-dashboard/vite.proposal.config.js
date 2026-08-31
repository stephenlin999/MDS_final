import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(root, "src") } },
  build: {
    outDir: path.resolve(root, ".proposal-dist"),
    emptyOutDir: true,
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    cssCodeSplit: false,
    rollupOptions: {
      input: path.resolve(root, "proposal.html"),
      output: {
        inlineDynamicImports: true,
        entryFileNames: "proposal.js",
        assetFileNames: "proposal[extname]",
      },
    },
  },
});
