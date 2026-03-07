export type ChatStreamFrame =
  | { type: "chunk"; text: string }
  | { type: "error"; message: string }
  | { type: "done" }

type FetchLike = typeof fetch

export function parseChatStreamFrame(frameText: string): ChatStreamFrame {
  try {
    return JSON.parse(frameText) as ChatStreamFrame
  } catch {
    throw new Error("invalid chat stream frame")
  }
}

export async function readStreamErrorCode(response: Response): Promise<string | undefined> {
  try {
    const payload = (await response.clone().json()) as { error?: { code?: string } }
    return payload.error?.code
  } catch {
    return undefined
  }
}

export function shouldRetryWithFreshNonce(status: number, errorCode: string | undefined): boolean {
  return status === 403 && errorCode === "INVALID_NONCE"
}

async function fetchBootstrapNonce(fetchFn: FetchLike): Promise<string> {
  const response = await fetchFn("/api/bootstrap")
  if (!response.ok) {
    throw new Error(`bootstrap request failed (${response.status})`)
  }

  const payload = (await response.json()) as { local_nonce?: string }
  if (typeof payload.local_nonce !== "string" || payload.local_nonce.length === 0) {
    throw new Error("bootstrap response missing local nonce")
  }

  return payload.local_nonce
}

async function postChatStreamRequest(
  fetchFn: FetchLike,
  promptText: string,
  controller: AbortController,
  localNonce: string,
): Promise<Response> {
  return fetchFn("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Squidbot-Local-Nonce": localNonce
    },
    body: JSON.stringify({ prompt: promptText }),
    signal: controller.signal
  })
}

export async function requestChatStreamResponse({
  promptText,
  controller,
  nonce,
  fetchFn = fetch
}: {
  promptText: string
  controller: AbortController
  nonce: string | null
  fetchFn?: FetchLike
}): Promise<{ response: Response; nonce: string }> {
  let activeNonce = nonce ?? await fetchBootstrapNonce(fetchFn)
  let response = await postChatStreamRequest(fetchFn, promptText, controller, activeNonce)

  if (response.status !== 403) {
    return { response, nonce: activeNonce }
  }

  const errorCode = await readStreamErrorCode(response)
  if (!shouldRetryWithFreshNonce(response.status, errorCode)) {
    return { response, nonce: activeNonce }
  }

  activeNonce = await fetchBootstrapNonce(fetchFn)
  response = await postChatStreamRequest(fetchFn, promptText, controller, activeNonce)
  return { response, nonce: activeNonce }
}

export async function collectChatStreamFrames(
  response: Response,
  onFrame?: (frame: ChatStreamFrame) => void,
): Promise<Array<ChatStreamFrame>> {
  if (response.body === null) {
    throw new Error(`chat stream request failed (${response.status})`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const frames: Array<ChatStreamFrame> = []
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      buffer += decoder.decode()
    } else {
      buffer += decoder.decode(value, { stream: true })
    }

    let newlineIndex = buffer.indexOf("\n")
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex).trim()
      buffer = buffer.slice(newlineIndex + 1)

      if (line.length > 0) {
        const frame = parseChatStreamFrame(line)
        frames.push(frame)
        onFrame?.(frame)
        if (frame.type === "done") {
          return frames
        }
      }

      newlineIndex = buffer.indexOf("\n")
    }

    if (done) {
      const trailing = buffer.trim()
      if (trailing.length > 0) {
        const frame = parseChatStreamFrame(trailing)
        frames.push(frame)
        onFrame?.(frame)
      }
      return frames
    }
  }
}
