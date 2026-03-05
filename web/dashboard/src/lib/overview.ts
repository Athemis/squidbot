export type OverviewPayload = {
  started_at: string
  channels: Array<{
    name: string
    enabled: boolean
    connected: boolean
    error: string | null
  }>
  active_sessions: Array<{
    session_id: string
    channel: string
    sender_id: string | null
    started_at: string
    message_count: number
  }>
  cron_jobs: number
}

export type OverviewViewModel = {
  startedAt: string
  cronJobs: number
  channels: Array<{
    name: string
    enabled: boolean
    connected: boolean
    error: string | null
    statusLabel: "connected" | "degraded" | "disconnected"
  }>
  sessions: Array<{
    sessionId: string
    channel: string
    senderId: string | null
    startedAt: string
    messageCount: number
  }>
}

export function mapOverviewPayload(payload: OverviewPayload): OverviewViewModel {
  return {
    startedAt: payload.started_at,
    cronJobs: payload.cron_jobs,
    channels: payload.channels.map((channel) => ({
      ...channel,
      statusLabel: channel.connected ? "connected" : channel.error ? "degraded" : "disconnected"
    })),
    sessions: payload.active_sessions.map((session) => ({
      sessionId: session.session_id,
      channel: session.channel,
      senderId: session.sender_id,
      startedAt: session.started_at,
      messageCount: session.message_count
    }))
  }
}
