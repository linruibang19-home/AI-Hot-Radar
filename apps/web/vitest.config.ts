import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// The `@/` alias comes from tsconfig paths, which Next resolves at build time
// but Vitest does not know about. Without this, any test importing a module
// that uses the alias fails to load.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
