<script lang="ts">
  import OverviewPage from "./routes/OverviewPage.svelte"
  import LogsPage from "./routes/LogsPage.svelte"
  import ConfigPage from "./routes/ConfigPage.svelte"
  import ChatPage from "./routes/ChatPage.svelte"

  type Route = "overview" | "logs" | "config" | "chat"
  let route: Route = "overview"
</script>

<main>
  <header>
    <h1>squidbot dashboard</h1>
    <nav>
      <button type="button" on:click={() => (route = "overview")}>Overview</button>
      <button type="button" on:click={() => (route = "logs")}>Logs</button>
      <button type="button" on:click={() => (route = "config")}>Config</button>
      <button type="button" on:click={() => (route = "chat")}>Chat</button>
    </nav>
  </header>

  {#if route === "overview"}
    <OverviewPage />
  {:else if route === "logs"}
    <LogsPage />
  {:else if route === "config"}
    <ConfigPage />
  {:else}
    <ChatPage />
  {/if}
</main>
