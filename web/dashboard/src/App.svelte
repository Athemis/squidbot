<script lang="ts">
  import { onDestroy } from "svelte"

  import {
    applyThemeState,
    createSystemThemeObserver,
    readStoredTheme,
    readSystemPrefersDark,
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
  let stopSystemThemeObserver: () => void = () => undefined

  function applyTheme(): void {
    if (typeof document === "undefined") {
      return
    }

    applyThemeState(document.documentElement, selectedTheme, prefersDark)
  }

  onDestroy(() => {
    stopSystemThemeObserver()
  })

  $: {
    applyTheme()
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

<main class="min-h-screen bg-surface-100-900 text-surface-900-50">
  <div class="dashboard-shell">
    <header class="dashboard-shell__topbar card preset-tonal-primary p-4 sm:p-5">
      <div class="dashboard-shell__heading">
        <p class="preset-typo-caption uppercase tracking-[0.24em] text-primary-700-300">squidbot</p>
        <p class="preset-typo-display-1 font-semibold tracking-tight text-surface-900-50">
          Control center
        </p>
        <p class="preset-typo-body-2 mt-1 text-surface-700-300">
          Live runtime overview, logs, config previews, and chat streaming in the active mona theme.
        </p>
      </div>

      <div class="dashboard-shell__controls">
        <nav class="dashboard-shell__tabs" aria-label="Primary">
          {#each routes as tab}
            <button
              type="button"
              class={`btn btn-sm dashboard-shell__tab ${route === tab.id ? "preset-filled-primary-500" : "preset-tonal-surface"}`}
              on:click={() => (route = tab.id)}
              aria-current={route === tab.id ? "page" : undefined}
            >
              {tab.label}
            </button>
          {/each}
        </nav>

        <label class="dashboard-shell__theme-select-wrap card preset-tonal-surface p-3 sm:p-4">
          <span class="dashboard-shell__theme-label text-surface-700-300">Mode</span>
          <select class="select select-sm" bind:value={selectedTheme}>
            <option value="system">System</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </label>
      </div>
    </header>

    <section class="dashboard-shell__content card preset-filled-surface-50-950 p-4 sm:p-6">
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
