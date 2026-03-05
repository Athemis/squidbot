<script lang="ts">
  import { onDestroy } from "svelte"

  type ChatStreamFrame =
    | { type: "chunk"; text: string }
    | { type: "error"; message: string }
    | { type: "done" }

  let prompt = ""
  let transcript = ""
  let error: string | null = null
  let sending = false
  let nonce: string | null = null
  let activeController: AbortController | null = null

  async function postChatStreamRequest(
    promptText: string,
    controller: AbortController,
    localNonce: string,
  ): Promise<Response> {
    return fetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Squidbot-Local-Nonce": localNonce
      },
      body: JSON.stringify({ prompt: promptText }),
      signal: controller.signal
    })
  }

  async function requestChatStream(
    promptText: string,
    controller: AbortController,
  ): Promise<Response> {
    const firstNonce = await ensureNonce()
    let response = await postChatStreamRequest(promptText, controller, firstNonce)

    if (response.status !== 403) {
      return response
    }

    let errorCode: string | undefined
    try {
      const payload = (await response.clone().json()) as { error?: { code?: string } }
      errorCode = payload.error?.code
    } catch {
      errorCode = undefined
    }

    if (errorCode !== "INVALID_NONCE") {
      return response
    }

    nonce = null
    const refreshedNonce = await ensureNonce()
    response = await postChatStreamRequest(promptText, controller, refreshedNonce)
    return response
  }

  async function ensureNonce(): Promise<string> {
    if (nonce !== null) {
      return nonce
    }

    const response = await fetch("/api/bootstrap")
    if (!response.ok) {
      throw new Error(`bootstrap request failed (${response.status})`)
    }
    const payload = (await response.json()) as { local_nonce?: string }
    if (typeof payload.local_nonce !== "string" || payload.local_nonce.length === 0) {
      throw new Error("bootstrap response missing local nonce")
    }
    nonce = payload.local_nonce
    return nonce
  }

  function applyFrame(frame: ChatStreamFrame): void {
    if (frame.type === "chunk") {
      transcript += frame.text
      return
    }
    if (frame.type === "error") {
      error = frame.message
    }
  }

  async function sendPrompt(): Promise<void> {
    if (sending) {
      return
    }

    const trimmedPrompt = prompt.trim()
    if (trimmedPrompt.length === 0) {
      return
    }

    sending = true
    error = null
    transcript = ""

    const controller = new AbortController()
    activeController = controller

    try {
      const response = await requestChatStream(trimmedPrompt, controller)
      if (!response.ok || response.body === null) {
        throw new Error(`chat stream request failed (${response.status})`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          break
        }

        buffer += decoder.decode(value, { stream: true })
        let newlineIndex = buffer.indexOf("\n")
        while (newlineIndex !== -1) {
          const line = buffer.slice(0, newlineIndex).trim()
          buffer = buffer.slice(newlineIndex + 1)

          if (line.length > 0) {
            const frame = JSON.parse(line) as ChatStreamFrame
            applyFrame(frame)
            if (frame.type === "done") {
              return
            }
          }
          newlineIndex = buffer.indexOf("\n")
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return
      }
      error = err instanceof Error ? err.message : "unknown chat error"
    } finally {
      sending = false
      if (activeController === controller) {
        activeController = null
      }
    }
  }

  onDestroy(() => {
    activeController?.abort()
  })
</script>

<section>
  <h2>Chat</h2>
  <form on:submit|preventDefault={() => void sendPrompt()}>
    <input bind:value={prompt} placeholder="Ask squidbot..." />
    <button type="submit" disabled={sending || prompt.trim().length === 0}>
      {#if sending}
        Sending...
      {:else}
        Send
      {/if}
    </button>
  </form>

  {#if error}
    <p>Chat error: {error}</p>
  {/if}

  <pre>{transcript}</pre>
</section>
