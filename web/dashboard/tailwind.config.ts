import type { Config } from "tailwindcss"
import { skeleton } from "@skeletonlabs/tw-plugin"

const config: Config = {
  content: ["./index.html", "./src/**/*.{svelte,ts}"],
  theme: {
    extend: {}
  },
  plugins: [
    skeleton({
      themes: {
        preset: ["skeleton"]
      }
    })
  ]
}

export default config
