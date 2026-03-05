<script lang="ts">
  import { onMount } from "svelte"

  import {
    mapOverviewPayload,
    type OverviewPayload,
    type OverviewViewModel
  } from "../lib/overview"
  import { choosePollingIntervalMs } from "../lib/polling"

  let overview: OverviewViewModel | null = null
  let error: string | null = null
  let isLoading = true
  let lastSuccessAt: string | null = null
  let timer: number | undefined

  function formatIso(ts: string): string {
    const date = new Date(ts)
    if (Number.isNaN(date.getTime())) {
      return ts
    }
    return date.toLocaleString()
  }

  function formatUptime(startedAtIso: string): string {
    const startedAt = new Date(startedAtIso)
    if (Number.isNaN(startedAt.getTime())) {
      return "unknown"
    }
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt.getTime()) / 1000))
    const days = Math.floor(elapsedSeconds / 86_400)
    const hours = Math.floor((elapsedSeconds % 86_400) / 3_600)
    const minutes = Math.floor((elapsedSeconds % 3_600) / 60)
    return `${days}d ${hours}h ${minutes}m`
  }

  async function refreshOverview(): Promise<void> {
    try {
      const response = await fetch("/api/overview")
      if (!response.ok) {
        throw new Error(`overview request failed (${response.status})`)
      }
      overview = mapOverviewPayload((await response.json()) as OverviewPayload)
      error = null
      lastSuccessAt = new Date().toISOString()
    } catch (err) {
      error = err instanceof Error ? err.message : "unknown overview error"
    } finally {
      isLoading = false
    }
  }

  function restartPollingTimer(): void {
    if (timer !== undefined) {
      window.clearInterval(timer)
    }
    timer = window.setInterval(() => {
      void refreshOverview()
    }, choosePollingIntervalMs())
  }

  onMount(() => {
    void refreshOverview()
    restartPollingTimer()

    const handleVisibilityChange = (): void => {
      restartPollingTimer()
    }
    document.addEventListener("visibilitychange", handleVisibilityChange)

    return () => {
      if (timer !== undefined) {
        window.clearInterval(timer)
      }
      document.removeEventListener("visibilitychange", handleVisibilityChange)
    }
  })
</script>

<section>
  <h2>Overview</h2>

  {#if error !== null && lastSuccessAt !== null}
    <p>
      Live refresh degraded (last successful update: {formatIso(lastSuccessAt)}). {error}
    </p>
  {/if}

  {#if isLoading}
    <p>Loading runtime status...</p>
  {:else if error}
    <p>Failed to load overview: {error}</p>
  {:else if overview}
    <p>Gateway started: {formatIso(overview.startedAt)}</p>
    <p>Uptime: {formatUptime(overview.startedAt)}</p>
    <p>Cron jobs: {overview.cronJobs}</p>

    <h3>Channels</h3>
    {#if overview.channels.length === 0}
      <p>No channels reported.</p>
    {:else}
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Enabled</th>
            <th>Status</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {#each overview.channels as channel}
            <tr>
              <td>{channel.name}</td>
              <td>{channel.enabled ? "yes" : "no"}</td>
              <td>{channel.statusLabel}</td>
              <td>{channel.error ?? "-"}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

    <h3>Active Sessions</h3>
    {#if overview.sessions.length === 0}
      <p>No active sessions.</p>
    {:else}
      <table>
        <thead>
          <tr>
            <th>Session</th>
            <th>Channel</th>
            <th>Sender</th>
            <th>Started</th>
            <th>Messages</th>
          </tr>
        </thead>
        <tbody>
          {#each overview.sessions as session}
            <tr>
              <td>{session.sessionId}</td>
              <td>{session.channel}</td>
              <td>{session.senderId ?? "-"}</td>
              <td>{formatIso(session.startedAt)}</td>
              <td>{session.messageCount}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}
</section>
