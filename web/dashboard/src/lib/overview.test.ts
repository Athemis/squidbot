import { describe, expect, it } from "vitest"

import { mapOverviewPayload } from "./overview"

describe("mapOverviewPayload", () => {
  it("maps channels and sessions deterministically", () => {
    const mapped = mapOverviewPayload({
      started_at: "2026-03-05T10:00:00+00:00",
      channels: [{ name: "matrix", enabled: true, connected: false, error: "timeout" }],
      active_sessions: [
        {
          session_id: "matrix:alice",
          channel: "matrix",
          sender_id: "@alice:example.org",
          started_at: "2026-03-05T10:01:00+00:00",
          message_count: 12
        }
      ],
      cron_jobs: 3
    })

    expect(mapped.channels[0].statusLabel).toBe("degraded")
    expect(mapped.sessions[0].sessionId).toBe("matrix:alice")
    expect(mapped.sessions[0].messageCount).toBe(12)
    expect(mapped.cronJobs).toBe(3)
  })
})
