import { describe, expect, it } from "vitest"

import {
  parseChatStreamFrame,
  readStreamErrorCode,
  shouldRetryWithFreshNonce
} from "./chat_stream"

describe("chat_stream", () => {
  it("parses valid chunk frames", () => {
    expect(parseChatStreamFrame('{"type":"chunk","text":"hello"}')).toEqual({
      type: "chunk",
      text: "hello"
    })
  })

  it("parses valid done frames", () => {
    expect(parseChatStreamFrame('{"type":"done"}')).toEqual({ type: "done" })
  })

  it("raises deterministic error for malformed frames", () => {
    expect(() => parseChatStreamFrame("not-json")).toThrowError("invalid chat stream frame")
  })

  it("extracts error code from response payload", async () => {
    const response = new Response(JSON.stringify({ error: { code: "INVALID_NONCE" } }), {
      status: 403,
      headers: { "Content-Type": "application/json" }
    })

    await expect(readStreamErrorCode(response)).resolves.toBe("INVALID_NONCE")
  })

  it("returns undefined when response body is not json", async () => {
    const response = new Response("<html>forbidden</html>", {
      status: 403,
      headers: { "Content-Type": "text/html" }
    })

    await expect(readStreamErrorCode(response)).resolves.toBeUndefined()
  })

  it("retries only for invalid nonce responses", () => {
    expect(shouldRetryWithFreshNonce(403, "INVALID_NONCE")).toBe(true)
    expect(shouldRetryWithFreshNonce(403, "OTHER")).toBe(false)
    expect(shouldRetryWithFreshNonce(500, "INVALID_NONCE")).toBe(false)
  })
})
