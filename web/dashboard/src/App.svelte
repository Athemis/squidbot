<script lang="ts">
  import { onDestroy } from "svelte"

  import {
    createSystemThemeObserver,
    readStoredTheme,
    readSystemPrefersDark,
    resolveAppliedTheme,
    type Theme,
    writeStoredTheme
  } from "./lib/theme"
  import OverviewPage from "./routes/OverviewPage.svelte"
  import LogsPage from "./routes/LogsPage.svelte"
  import ConfigPage from "./routes/ConfigPage.svelte"
  import ChatPage from "./routes/ChatPage.svelte"

  type Route = "overview" | "logs" | "config" | "chat"
  const routes: Array<{ id: Route; label: string }> = [
    { id: "overview", label: "Overview" },
    { id: "logs", label: "Logs" },
    { id: "config", label: "Config" },
    { id: "chat", label: "Chat" }
  ]

  let route: Route = "overview"

  let selectedTheme: Theme = readStoredTheme()
  let prefersDark = readSystemPrefersDark()
  let appliedTheme: "light" | "dark" = "light"
  let stopSystemThemeObserver: () => void = () => undefined

  function applyTheme(theme: "light" | "dark"): void {
    if (typeof document === "undefined") {
      return
    }

    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
  }

  onDestroy(() => {
    stopSystemThemeObserver()
  })

  $: appliedTheme = resolveAppliedTheme(selectedTheme, prefersDark)

  $: {
    applyTheme(appliedTheme)
  }

  $: writeStoredTheme(selectedTheme)

  $: {
    stopSystemThemeObserver()
    stopSystemThemeObserver = () => undefined

    if (selectedTheme === "system") {
      prefersDark = readSystemPrefersDark()
      stopSystemThemeObserver = createSystemThemeObserver(undefined, (nextPrefersDark) => {
        prefersDark = nextPrefersDark
      })
    }
  }
</script>

<main class="bg-surface-100-900 text-surface-900-50">
  <div class="dashboard-shell">
    <header class="dashboard-shell__topbar border border-surface-200-700 bg-surface-50-950">
      <div class="dashboard-shell__heading">
        <h1 class="text-lg font-semibold tracking-tight text-surface-900-50 sm:text-xl">
          squidbot dashboard
        </h1>
      </div>

      <div class="dashboard-shell__controls">
        <nav class="dashboard-shell__tabs" aria-label="Primary">
          {#each routes as tab}
            <button
              type="button"
              class={`dashboard-shell__tab ${route === tab.id ? "dashboard-shell__tab--active" : ""}`}
              on:click={() => (route = tab.id)}
              aria-current={route === tab.id ? "page" : undefined}
            >
              {tab.label}
            </button>
          {/each}
        </nav>

        <label
          class="dashboard-shell__theme-select-wrap border border-surface-200-700 bg-surface-100-900"
        >
          <span class="dashboard-shell__theme-label text-surface-700-300">Theme</span>
          <select class="select select-sm" bind:value={selectedTheme}>
            <option value="system">System</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </label>
      </div>
    </header>

    <section class="dashboard-shell__content border border-surface-200-700 bg-surface-50-950">
      {#if route === "overview"}
        <OverviewPage />
      {:else if route === "logs"}
        <LogsPage />
      {:else if route === "config"}
        <ConfigPage />
      {:else}
        <ChatPage />
      {/if}
    </section>
  </div>
</main>
