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

  function countChannelsByTone(
    channels: OverviewViewModel["channels"],
    tone: "ok" | "warn" | "error" | "idle"
  ): number {
    return channels.filter((channel) => statusTone(channel) === tone).length
  }

  function totalSessionMessages(sessions: OverviewViewModel["sessions"]): number {
    return sessions.reduce((total, session) => total + session.messageCount, 0)
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
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <div class="card preset-tonal-surface p-4 sm:p-5">
        <div class="skeleton h-4 w-20"></div>
        <div class="mt-3 skeleton h-8 w-24"></div>
      </div>
      <div class="card preset-tonal-surface p-4 sm:p-5">
        <div class="skeleton h-4 w-16"></div>
        <div class="mt-3 skeleton h-8 w-28"></div>
      </div>
      <div class="card preset-tonal-surface p-4 sm:p-5">
        <div class="skeleton h-4 w-24"></div>
        <div class="mt-3 skeleton h-8 w-16"></div>
      </div>
      <div class="card preset-tonal-surface p-4 sm:p-5">
        <div class="skeleton h-4 w-20"></div>
        <div class="mt-3 skeleton h-8 w-20"></div>
      </div>
    </div>

    <div class="card preset-tonal-surface grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-6">
      {#each Array(6) as _, index}
        <div class="space-y-2" aria-hidden="true">
          <div class="skeleton h-3 w-20"></div>
          <div class={`skeleton h-7 ${index === 0 ? "w-24" : "w-16"}`}></div>
        </div>
      {/each}
    </div>

    <div class="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.35fr)]">
      <div class="card preset-tonal-surface p-4 sm:p-5">
        <div class="skeleton h-5 w-28"></div>
        <div class="mt-4 space-y-2">
          <div class="skeleton h-10 w-full"></div>
          <div class="skeleton h-10 w-full"></div>
          <div class="skeleton h-10 w-full"></div>
        </div>
      </div>
      <div class="card preset-tonal-surface p-4 sm:p-5">
        <div class="skeleton h-5 w-32"></div>
        <div class="mt-4 space-y-2">
          <div class="skeleton h-10 w-full"></div>
          <div class="skeleton h-10 w-full"></div>
          <div class="skeleton h-10 w-full"></div>
        </div>
      </div>
    </div>
    <p class="preset-typo-body-2 text-surface-700-300">Loading runtime status...</p>
  {:else if overview}
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Gateway started" value={formatIso(overview.startedAt)} detail="Runtime" />
      <MetricCard label="Uptime" value={formatUptime(overview.startedAt)} detail="Live" />
      <MetricCard label="Active sessions" value={overview.sessions.length} detail="Open now" />
      <MetricCard label="Cron jobs" value={overview.cronJobs} detail="Scheduled" />
    </div>

    <article class="card preset-tonal-surface overflow-hidden">
      <div class="flex flex-col gap-4 border-b border-surface-200-800 p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
        <div class="space-y-1">
          <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Status strip</p>
          <p class="preset-typo-body-2 max-w-3xl text-surface-900-50">
            Live operator snapshot for channel health, session load, and gateway activity.
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="badge preset-tonal-surface border-0">
            Last update {lastSuccessAt ? formatIso(lastSuccessAt) : "pending"}
          </span>
          <span class="badge preset-tonal-primary border-0">{overview.channels.length} channels tracked</span>
          <span class="badge preset-tonal-surface border-0">{totalSessionMessages(overview.sessions)} messages in flight</span>
        </div>
      </div>

      <div class="grid gap-3 p-4 sm:grid-cols-2 sm:p-5 xl:grid-cols-6">
        <div class="card preset-filled-surface-50-950 space-y-1 p-3">
          <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Healthy</p>
          <p class="text-xl font-semibold text-surface-900-50">{countChannelsByTone(overview.channels, "ok")}</p>
        </div>
        <div class="card preset-filled-surface-50-950 space-y-1 p-3">
          <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Degraded</p>
          <p class="text-xl font-semibold text-surface-900-50">{countChannelsByTone(overview.channels, "warn")}</p>
        </div>
        <div class="card preset-filled-surface-50-950 space-y-1 p-3">
          <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Blocked</p>
          <p class="text-xl font-semibold text-surface-900-50">{countChannelsByTone(overview.channels, "error")}</p>
        </div>
        <div class="card preset-filled-surface-50-950 space-y-1 p-3">
          <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Disabled</p>
          <p class="text-xl font-semibold text-surface-900-50">{countChannelsByTone(overview.channels, "idle")}</p>
        </div>
        <div class="card preset-filled-surface-50-950 space-y-1 p-3">
          <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Sessions</p>
          <p class="text-xl font-semibold text-surface-900-50">{overview.sessions.length}</p>
        </div>
        <div class="card preset-filled-surface-50-950 space-y-1 p-3">
          <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Cron jobs</p>
          <p class="text-xl font-semibold text-surface-900-50">{overview.cronJobs}</p>
        </div>
      </div>

      <div class="flex flex-wrap gap-2 px-4 pb-4 sm:px-5 sm:pb-5">
        {#each overview.channels as channel}
          <div class="card preset-filled-surface-50-950 flex items-center gap-2 px-3 py-2">
            <span class="preset-typo-caption uppercase tracking-[0.14em] text-surface-700-300">{channel.name}</span>
            <StatusChip tone={statusTone(channel)} label={statusLabel(channel)} />
          </div>
        {/each}
      </div>
    </article>

    <div class="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.35fr)]">
      <section class="card preset-tonal-surface space-y-4 p-4 sm:p-5">
        <SectionTitle title="Channels" subtitle="Connection health, enablement, and runtime errors by adapter." />
        <div class="flex flex-wrap gap-2">
          <span class="badge preset-tonal-surface border-0">{overview.channels.length} total</span>
          <span class="badge preset-tonal-success border-0">{countChannelsByTone(overview.channels, "ok")} healthy</span>
          <span class="badge preset-tonal-warning border-0">{countChannelsByTone(overview.channels, "warn")} degraded</span>
          <span class="badge preset-tonal-error border-0">{countChannelsByTone(overview.channels, "error")} blocked</span>
        </div>

        {#if overview.channels.length === 0}
          <div class="card preset-filled-surface-50-950 p-4">
            <p class="preset-typo-body-2 text-surface-700-300">No channels reported.</p>
          </div>
        {:else}
          <div class="table-wrap">
            <table class="table">
              <caption class="sr-only">Channel health and runtime errors by adapter.</caption>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>State</th>
                  <th>Enabled</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody class="[&>tr:hover]:preset-tonal-primary">
                {#each overview.channels as channel}
                  <tr>
                    <td class="font-medium">{channel.name}</td>
                    <td>
                      <StatusChip tone={statusTone(channel)} label={statusLabel(channel)} />
                    </td>
                    <td>{channel.enabled ? "yes" : "no"}</td>
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

      <section class="card preset-tonal-surface space-y-4 p-4 sm:p-5">
        <SectionTitle title="Active Sessions" subtitle="Recent inbound session activity grouped into one operator table." />
        <div class="flex flex-wrap gap-2">
          <span class="badge preset-tonal-surface border-0">{overview.sessions.length} open</span>
          <span class="badge preset-tonal-primary border-0">{totalSessionMessages(overview.sessions)} messages</span>
        </div>

        {#if overview.sessions.length === 0}
          <div class="card preset-filled-surface-50-950 p-4">
            <p class="preset-typo-body-2 text-surface-700-300">No active sessions.</p>
          </div>
        {:else}
          <div class="table-wrap">
            <table class="table">
              <caption class="sr-only">Recent inbound session activity grouped into one operator table.</caption>
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
    </div>
  {:else if error}
    <div class="alert preset-tonal-error border-0" role="alert" aria-live="assertive">
      <p>Failed to load overview: {error}</p>
    </div>
  {/if}
</PageShell>
