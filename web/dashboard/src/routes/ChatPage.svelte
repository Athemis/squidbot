<script lang="ts">
  import { onDestroy } from "svelte"

  import {
    parseChatStreamFrame,
    readStreamErrorCode,
    shouldRetryWithFreshNonce,
    type ChatStreamFrame
  } from "../lib/chat_stream"
  import PageShell from "../lib/ui/PageShell.svelte"
  import SectionTitle from "../lib/ui/SectionTitle.svelte"

  let prompt = ""
  let transcript = ""
  let error: string | null = null
  let sending = false
  let receivedDoneFrame = false
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

    const errorCode = await readStreamErrorCode(response)

    if (!shouldRetryWithFreshNonce(response.status, errorCode)) {
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
      return
    }
    if (frame.type === "done") {
      receivedDoneFrame = true
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
    receivedDoneFrame = false

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
            applyFrame(frame)
            if (frame.type === "done") {
              return
            }
          }
          newlineIndex = buffer.indexOf("\n")
        }

        if (done) {
          const trailing = buffer.trim()
          if (trailing.length > 0) {
            const frame = parseChatStreamFrame(trailing)
            applyFrame(frame)
          }
          break
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

  $: trimmedPrompt = prompt.trim()
  $: canSendPrompt = !sending && trimmedPrompt.length > 0
  $: streamState = error
    ? "error"
    : sending
      ? "streaming"
      : receivedDoneFrame
        ? "done"
        : "idle"
</script>

<PageShell title="Chat">
  <section class="space-y-3">
    <SectionTitle
      title="Conversation stream"
      subtitle="Submit a prompt and watch streamed chunks render in real time."
    />

    <article class="space-y-3 rounded-xl border border-surface-200-700 bg-surface-100-900 p-4">
      <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p class="font-medium text-surface-900-50">Response output</p>
        {#if streamState === "streaming"}
          <span class="badge variant-soft-primary">Streaming...</span>
        {:else if streamState === "done"}
          <span class="badge variant-soft-success">Complete</span>
        {:else if streamState === "error"}
          <span class="badge variant-soft-error">Stream failed</span>
        {:else}
          <span class="badge variant-soft-surface">Idle</span>
        {/if}
      </div>

      <div
        class="min-h-56 rounded-lg border border-surface-200-700 bg-surface-50-950 p-4"
        aria-live="polite"
      >
        {#if transcript.length === 0}
          <p class="text-sm text-surface-700-300">
            {#if sending}
              Waiting for first stream chunk...
            {:else}
              No response yet. Send a prompt to start streaming output.
            {/if}
          </p>
        {:else}
          <pre class="overflow-x-auto whitespace-pre-wrap break-words text-sm text-surface-900-50">{transcript}</pre>
        {/if}
      </div>
    </article>
  </section>

  <section class="space-y-3">
    <SectionTitle
      title="Prompt input"
      subtitle="Input and action controls stay visible while streaming or showing errors."
    />

    <form
      class="space-y-3 rounded-xl border border-surface-200-700 bg-surface-100-900 p-4"
      on:submit|preventDefault={() => void sendPrompt()}
    >
      <label class="space-y-1 text-sm font-medium text-surface-700-300" for="chat-prompt-input">
        Prompt
        <textarea
          id="chat-prompt-input"
          class="textarea min-h-28 w-full"
          bind:value={prompt}
          disabled={sending}
          placeholder="Ask squidbot..."
        ></textarea>
      </label>

      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-xs text-surface-700-300">
          {#if sending}
            Sending request and parsing stream frames...
          {:else if error}
            Last request failed. Edit prompt and retry.
          {:else}
            Ready to send.
          {/if}
        </p>
        <button class="btn btn-sm variant-filled-surface" type="submit" disabled={!canSendPrompt}>
          {#if sending}
            Sending...
          {:else}
            Send
          {/if}
        </button>
      </div>
    </form>

    {#if error}
      <div class="alert variant-soft-error">
        <p>Chat error: {error}</p>
      </div>
    {/if}
  </section>
</PageShell>
