<script lang="ts">
  import { onDestroy, tick } from "svelte"

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
  let contentPanel: HTMLElement | null = null
  let tabButtons: Array<HTMLButtonElement | null> = []

  let selectedTheme: Theme = readStoredTheme()
  let prefersDark = readSystemPrefersDark()
  let stopSystemThemeObserver: () => void = () => undefined

  async function selectRoute(nextRoute: Route, focusTarget: "panel" | "tab" = "panel"): Promise<void> {
    route = nextRoute
    await tick()
    if (focusTarget === "tab") {
      const nextIndex = routes.findIndex((tab) => tab.id === nextRoute)
      tabButtons[nextIndex]?.focus()
      return
    }

    contentPanel?.focus()
  }

  async function handleTabKeydown(event: KeyboardEvent, index: number): Promise<void> {
    if (event.key === "ArrowRight") {
      event.preventDefault()
      await selectRoute(routes[(index + 1) % routes.length].id, "tab")
      return
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault()
      await selectRoute(routes[(index - 1 + routes.length) % routes.length].id, "tab")
      return
    }

    if (event.key === "Home") {
      event.preventDefault()
      await selectRoute(routes[0].id, "tab")
      return
    }

    if (event.key === "End") {
      event.preventDefault()
      await selectRoute(routes[routes.length - 1].id, "tab")
    }
  }

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
  <div class="mx-auto flex w-full max-w-7xl flex-col gap-4 p-3 sm:gap-5 sm:p-5 xl:py-6">
    <header class="space-y-4">
      <section class="card preset-tonal-primary grid gap-4 p-4 sm:p-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(20rem,1fr)] xl:items-center">
        <div class="space-y-3 min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <span class="badge preset-tonal-surface border-0">localhost workspace</span>
            <span class="badge preset-tonal-primary border-0">theme mona</span>
          </div>
          <div class="space-y-1">
            <p class="preset-typo-caption uppercase tracking-[0.24em] text-primary-700-300">squidbot</p>
            <p class="preset-typo-display-1 font-semibold tracking-tight text-surface-900-50">
              Control center
            </p>
            <p class="preset-typo-body-2 max-w-2xl text-surface-700-300">
              Runtime overview, logs, config previews, and operator chat in one local workspace.
            </p>
          </div>
        </div>

        <div class="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div class="card preset-tonal-surface space-y-3 p-3 sm:p-4">
            <div class="flex items-center justify-between gap-2">
              <p class="preset-typo-caption uppercase tracking-[0.2em] text-surface-700-300">Workspace</p>
              <span class="badge preset-tonal-surface border-0">4 views</span>
            </div>
            <div class="flex flex-wrap gap-2" role="tablist" aria-label="Primary workspace views">
              {#each routes as tab}
                <button
                  bind:this={tabButtons[routes.findIndex((routeOption) => routeOption.id === tab.id)]}
                  type="button"
                  class={`btn btn-sm flex-1 sm:flex-none ${route === tab.id ? "preset-filled-primary-500" : "preset-tonal-surface"}`}
                  id={`dashboard-tab-${tab.id}`}
                  role="tab"
                  aria-selected={route === tab.id}
                  aria-controls={`dashboard-panel-${tab.id}`}
                  tabindex={route === tab.id ? 0 : -1}
                  on:click={() => void selectRoute(tab.id)}
                  on:keydown={(event) => void handleTabKeydown(event, routes.findIndex((routeOption) => routeOption.id === tab.id))}
                >
                  {tab.label}
                </button>
              {/each}
            </div>
          </div>

          <label class="card preset-filled-surface-50-950 flex min-w-44 items-center gap-3 p-3 sm:p-4">
            <span class="preset-typo-caption uppercase tracking-[0.2em] text-surface-700-300">Mode</span>
            <select class="select select-sm flex-1" bind:value={selectedTheme}>
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
        </div>
      </section>
    </header>

    <div
      bind:this={contentPanel}
      class="card preset-filled-surface-50-950 min-w-0 p-4 focus:outline-none sm:p-6 xl:p-7"
      id={`dashboard-panel-${route}`}
      role="tabpanel"
      aria-labelledby={`dashboard-tab-${route}`}
      tabindex="0"
    >
      {#if route === "overview"}
        <OverviewPage />
      {:else if route === "logs"}
        <LogsPage />
      {:else if route === "config"}
        <ConfigPage />
      {:else}
        <ChatPage />
      {/if}
    </div>
  </div>
</main>
