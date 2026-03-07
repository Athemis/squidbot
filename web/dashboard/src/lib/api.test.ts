import { afterEach, describe, expect, it, vi } from "vitest"

import { patchConfig } from "./api"

describe("patchConfig", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("adds nonce header on patch config", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await patchConfig({ heartbeat: { interval_minutes: 45 } }, "nonce-123")

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/config",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          "X-Squidbot-Local-Nonce": "nonce-123"
        })
      })
    )
  })
})
