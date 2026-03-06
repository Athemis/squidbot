import { defineConfig } from "vite"
import { svelte } from "@sveltejs/vite-plugin-svelte"

export default defineConfig({
  plugins: [svelte()],
  css: {
    postcss: "./postcss.config.js"
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"]
  }
})
