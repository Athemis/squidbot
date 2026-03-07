import { describe, expect, it } from "vitest"

import {
  collectChatStreamFrames,
  parseChatStreamFrame,
  requestChatStreamResponse,
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

  it("refreshes the nonce once after an invalid nonce response", async () => {
    const responses = [
      new Response(JSON.stringify({ local_nonce: "nonce-1" }), { status: 200 }),
      new Response(JSON.stringify({ error: { code: "INVALID_NONCE" } }), { status: 403 }),
      new Response(JSON.stringify({ local_nonce: "nonce-2" }), { status: 200 }),
      new Response("ok", { status: 200 })
    ]

    const fetchMock = async () => {
      const next = responses.shift()
      if (next === undefined) {
        throw new Error("unexpected fetch")
      }
      return next
    }

    const result = await requestChatStreamResponse({
      promptText: "hello",
      controller: new AbortController(),
      nonce: null,
      fetchFn: fetchMock
    })

    expect(result.response.status).toBe(200)
    expect(result.nonce).toBe("nonce-2")
  })

  it("collects parsed frames from a newline-delimited response body", async () => {
    const seenFrames: Array<string> = []
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"type":"chunk","text":"hi"}\n'))
        controller.enqueue(new TextEncoder().encode('{"type":"done"}\n'))
        controller.close()
      }
    })

    const response = new Response(stream, { status: 200 })

    await expect(collectChatStreamFrames(response, (frame) => {
      seenFrames.push(frame.type)
    })).resolves.toEqual([
      { type: "chunk", text: "hi" },
      { type: "done" }
    ])
    expect(seenFrames).toEqual(["chunk", "done"])
  })
})
