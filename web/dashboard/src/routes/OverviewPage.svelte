<script lang="ts">
  import { onMount } from "svelte"

  import MetricCard from "../lib/ui/MetricCard.svelte"
  import PageShell from "../lib/ui/PageShell.svelte"
  import SectionTitle from "../lib/ui/SectionTitle.svelte"
  import StatusChip from "../lib/ui/StatusChip.svelte"
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
  let refreshGeneration = 0

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

  function statusTone(channel: OverviewViewModel["channels"][number]): "ok" | "warn" | "error" | "idle" {
    if (!channel.enabled) {
      return "idle"
    }
    if (channel.statusLabel === "connected") {
      return "ok"
    }
    if (channel.statusLabel === "degraded") {
      return "warn"
    }
    return "error"
  }

  function statusLabel(channel: OverviewViewModel["channels"][number]): string {
    if (!channel.enabled) {
      return "disabled"
    }

    return channel.statusLabel
  }

  async function refreshOverview(): Promise<void> {
    const requestGeneration = refreshGeneration + 1
    refreshGeneration = requestGeneration

    try {
      const response = await fetch("/api/overview")
      if (!response.ok) {
        throw new Error(`overview request failed (${response.status})`)
      }
      const payload = mapOverviewPayload((await response.json()) as OverviewPayload)
      if (requestGeneration === refreshGeneration) {
        overview = payload
        error = null
        lastSuccessAt = new Date().toISOString()
      }
    } catch (err) {
      if (requestGeneration === refreshGeneration) {
        error = err instanceof Error ? err.message : "unknown overview error"
      }
    } finally {
      if (requestGeneration === refreshGeneration) {
        isLoading = false
      }
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

<PageShell title="Overview">
  {#if error !== null && lastSuccessAt !== null}
    <div class="alert preset-tonal-warning border-0" role="alert" aria-live="assertive">
      <p>Live refresh degraded (last successful update: {formatIso(lastSuccessAt)}). {error}</p>
    </div>
  {/if}

  {#if isLoading && overview === null}
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <div class="card preset-tonal-surface p-5">
        <div class="skeleton h-4 w-24"></div>
        <div class="mt-3 skeleton h-8 w-32"></div>
      </div>
      <div class="card preset-tonal-surface p-5">
        <div class="skeleton h-4 w-16"></div>
        <div class="mt-3 skeleton h-8 w-28"></div>
      </div>
      <div class="card preset-tonal-surface p-5 sm:col-span-2 lg:col-span-1">
        <div class="skeleton h-4 w-24"></div>
        <div class="mt-3 skeleton h-8 w-20"></div>
      </div>
    </div>
    <p class="preset-typo-body-2 text-surface-700-300">Loading runtime status...</p>
  {:else if overview}
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <MetricCard label="Gateway started" value={formatIso(overview.startedAt)} />
      <MetricCard label="Uptime" value={formatUptime(overview.startedAt)} />
      <MetricCard label="Cron jobs" value={overview.cronJobs} />
    </div>

    <article class="card preset-tonal-primary flex flex-col gap-3 p-5 lg:flex-row lg:items-center lg:justify-between">
      <div class="space-y-1">
        <p class="preset-typo-caption uppercase tracking-[0.24em] text-primary-700-300">Runtime pulse</p>
        <p class="preset-typo-body-1 text-surface-900-50">
          Monitor channel health, session activity, and current gateway uptime from one surface.
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="badge preset-tonal-surface border-0">Last update {lastSuccessAt ? formatIso(lastSuccessAt) : "pending"}</span>
        <span class="badge preset-tonal-primary border-0">{overview.channels.length} channels</span>
        <span class="badge preset-tonal-surface border-0">{overview.sessions.length} sessions</span>
      </div>
    </article>

    <section class="space-y-3">
      <SectionTitle title="Channels" subtitle="Connection health and runtime errors by channel." />
      {#if overview.channels.length === 0}
        <div class="card preset-tonal-surface p-5">
          <p class="preset-typo-body-2 text-surface-700-300">No channels reported.</p>
        </div>
      {:else}
        <div class="table-wrap card preset-tonal-surface p-2 sm:p-3">
          <table class="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Enabled</th>
                <th>Status</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody class="[&>tr:hover]:preset-tonal-primary">
              {#each overview.channels as channel}
                <tr>
                  <td class="font-medium">{channel.name}</td>
                  <td>{channel.enabled ? "yes" : "no"}</td>
                  <td>
                    <StatusChip tone={statusTone(channel)} label={statusLabel(channel)} />
                  </td>
                  <td class="max-w-80 whitespace-pre-wrap break-words" title={channel.error ?? undefined}>
                    {channel.error ?? "-"}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </section>

    <section class="space-y-3">
      <SectionTitle title="Active Sessions" subtitle="Recent inbound session activity across channels." />
      {#if overview.sessions.length === 0}
        <div class="card preset-tonal-surface p-5">
          <p class="preset-typo-body-2 text-surface-700-300">No active sessions.</p>
        </div>
      {:else}
        <div class="table-wrap card preset-tonal-surface p-2 sm:p-3">
          <table class="table">
            <thead>
              <tr>
                <th>Session</th>
                <th>Channel</th>
                <th>Sender</th>
                <th>Started</th>
                <th>Messages</th>
              </tr>
            </thead>
            <tbody class="[&>tr:hover]:preset-tonal-primary">
              {#each overview.sessions as session}
                <tr>
                  <td class="font-mono text-xs">{session.sessionId}</td>
                  <td>{session.channel}</td>
                  <td>{session.senderId ?? "-"}</td>
                  <td>{formatIso(session.startedAt)}</td>
                  <td>{session.messageCount}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </section>
  {:else if error}
    <div class="alert preset-tonal-error border-0" role="alert" aria-live="assertive">
      <p>Failed to load overview: {error}</p>
    </div>
  {/if}
</PageShell>
