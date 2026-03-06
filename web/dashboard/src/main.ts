import { mount } from "svelte"
import App from "./App.svelte"
import "./app.css"

import { applyThemeState, readStoredTheme, readSystemPrefersDark } from "./lib/theme"

const target = document.getElementById("app")
if (target === null) {
  throw new Error("Dashboard bootstrap failed: #app element not found")
}

applyThemeState(document.documentElement, readStoredTheme(), readSystemPrefersDark())

const app = mount(App, {
  target
})

export default app
