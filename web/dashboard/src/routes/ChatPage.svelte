<script lang="ts">
  import { onDestroy } from "svelte"

  import {
    collectChatStreamFrames,
    requestChatStreamResponse,
    readStreamErrorCode,
    shouldRetryWithFreshNonce,
    type ChatStreamFrame
  } from "../lib/chat_stream"
  import PageShell from "../lib/ui/PageShell.svelte"
  import SectionTitle from "../lib/ui/SectionTitle.svelte"
  import StatusChip from "../lib/ui/StatusChip.svelte"

  let prompt = ""
  let transcript = ""
  let error: string | null = null
  let sending = false
  let receivedDoneFrame = false
  let nonce: string | null = null
  let activeController: AbortController | null = null
  let streamTone: "ok" | "warn" | "error" | "idle" = "idle"

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
      const result = await requestChatStreamResponse({
        promptText: trimmedPrompt,
        controller,
        nonce
      })
      nonce = result.nonce

      const response = result.response
      if (!response.ok || response.body === null) {
        const errorCode = await readStreamErrorCode(response)
        if (shouldRetryWithFreshNonce(response.status, errorCode)) {
          nonce = null
        }
        throw new Error(`chat stream request failed (${response.status})`)
      }

      await collectChatStreamFrames(response, (frame: ChatStreamFrame) => {
        applyFrame(frame)
      })
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

  $: streamTone = error ? "error" : sending ? "warn" : receivedDoneFrame ? "ok" : "idle"
</script>

<PageShell title="Chat">
  <section class="space-y-3">
    <SectionTitle
      title="Conversation workspace"
      subtitle="Streaming output, request state, and compose controls now share the same operator dashboard language."
    />

    <div class="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.72fr)]">
      <article class="card preset-tonal-primary overflow-hidden">
        <div class="flex flex-col gap-4 border-b border-primary-200-800 p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
          <div class="space-y-1">
            <p class="preset-typo-caption uppercase tracking-[0.24em] text-primary-700-300">Response output</p>
            <p class="preset-typo-body-2 max-w-3xl text-surface-900-50">Live streamed chunks accumulate here.</p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <StatusChip
              tone={streamTone}
              label={streamState === "streaming"
                ? "Streaming"
                : streamState === "done"
                  ? "Complete"
                  : streamState === "error"
                    ? "Stream failed"
                    : "Idle"}
            />
            <span class="badge preset-tonal-surface border-0">Chunked SSE preview</span>
          </div>
        </div>

        <div class="space-y-4 p-4 sm:p-5">
          <div class="grid gap-3 sm:grid-cols-3">
            <div class="card preset-filled-surface-50-950 space-y-1 p-3">
              <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Mode</p>
              <p class="text-base font-semibold text-surface-900-50">Local chat stream</p>
            </div>
            <div class="card preset-filled-surface-50-950 space-y-1 p-3">
              <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Nonce</p>
              <p class="text-base font-semibold text-surface-900-50">Auto-refresh</p>
            </div>
            <div class="card preset-filled-surface-50-950 space-y-1 p-3">
              <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Transport</p>
              <p class="text-base font-semibold text-surface-900-50">Streaming POST</p>
            </div>
          </div>

          <div class="card preset-filled-surface-50-950 min-h-64 p-4 sm:p-5">
            {#if transcript.length === 0}
              <div class="flex min-h-56 items-center justify-center text-center">
                <p class="preset-typo-body-2 max-w-lg text-surface-700-300">
                  {#if sending}
                    Waiting for first stream chunk...
                  {:else}
                    No response yet. Send a prompt to start streaming output.
                  {/if}
                </p>
              </div>
            {:else}
              <pre class="overflow-x-auto whitespace-pre-wrap break-words text-sm leading-6 text-surface-900-50">{transcript}</pre>
            {/if}
          </div>
        </div>
      </article>

      <aside class="grid gap-4 content-start">
        <article class="card preset-tonal-surface space-y-4 p-4 sm:p-5">
          <div class="space-y-1">
            <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Request lifecycle</p>
            <p class="preset-typo-body-2 text-surface-700-300">Small operator cards keep state visible without moving transcript semantics.</p>
          </div>
          <div class="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
            <div class="card preset-filled-surface-50-950 space-y-1 p-3">
              <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Prompt</p>
              <p class="text-xl font-semibold text-surface-900-50">{trimmedPrompt.length}</p>
            </div>
            <div class="card preset-filled-surface-50-950 space-y-1 p-3">
              <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">State</p>
              <p class="text-xl font-semibold text-surface-900-50">{streamState}</p>
            </div>
            <div class="card preset-filled-surface-50-950 space-y-1 p-3">
              <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Done frame</p>
              <p class="text-xl font-semibold text-surface-900-50">{receivedDoneFrame ? "yes" : "no"}</p>
            </div>
          </div>
        </article>

        <article class="card preset-tonal-surface space-y-3 p-4 sm:p-5">
          <div class="space-y-1">
            <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Operator notes</p>
            <p class="preset-typo-body-2 text-surface-700-300">
              Stream behavior, retry logic, and error handling remain unchanged in this redesign slice.
            </p>
          </div>
          <div class="card preset-filled-surface-50-950 p-4">
            <p class="preset-typo-body-2 text-surface-700-300">
              Transcript output stays outside the live status region so screen readers only announce request state changes.
            </p>
          </div>
        </article>
      </aside>
    </div>
  </section>

  <section class="space-y-3">
    <SectionTitle
      title="Prompt composer"
      subtitle="Input and action controls stay visible while streaming or showing errors."
    />

    <form
      class="card preset-tonal-surface overflow-hidden"
      on:submit|preventDefault={() => void sendPrompt()}
    >
      <div class="flex flex-col gap-4 border-b border-surface-200-800 p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
        <div class="space-y-1">
          <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Compose request</p>
          <p class="preset-typo-body-2 max-w-3xl text-surface-900-50">Send one prompt at a time and keep the stream parser state visible.</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="badge preset-tonal-surface border-0">Prompt required</span>
          <span class="badge preset-tonal-primary border-0">Single active request</span>
        </div>
      </div>

      <div class="space-y-4 p-4 sm:p-5">
        <label class="space-y-1 text-sm font-medium text-surface-700-300" for="chat-prompt-input">
          Prompt
          <textarea
            id="chat-prompt-input"
            class="textarea min-h-32 w-full"
            bind:value={prompt}
            disabled={sending}
            placeholder="Ask squidbot..."
          ></textarea>
        </label>

        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="preset-typo-body-2 text-surface-700-300" role="status" aria-live="polite">
            {#if sending}
              Sending request and parsing stream frames...
            {:else if error}
              Last request failed. Edit prompt and retry.
            {:else if receivedDoneFrame}
              Response complete. Ready to send another prompt.
            {:else}
              Ready to send.
            {/if}
          </p>
          <button class="btn btn-sm preset-filled-primary-500" type="submit" disabled={!canSendPrompt}>
            {#if sending}
              Sending...
            {:else}
              Send
            {/if}
          </button>
        </div>
      </div>
    </form>

    {#if error}
      <div class="alert preset-tonal-error border-0" role="alert" aria-live="assertive">
        <p>Chat error: {error}</p>
      </div>
    {/if}
  </section>
</PageShell>
