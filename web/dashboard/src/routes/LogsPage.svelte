<script lang="ts">
  import PageShell from "../lib/ui/PageShell.svelte"
  import SectionTitle from "../lib/ui/SectionTitle.svelte"

  type PlaceholderState = "loading" | "empty" | "error"

  let placeholderState: PlaceholderState = "loading"

  const stateOptions: Array<{ label: string; value: PlaceholderState }> = [
    { label: "Loading", value: "loading" },
    { label: "Empty", value: "empty" },
    { label: "Error", value: "error" }
  ]
</script>

<PageShell title="Logs">
  <section class="space-y-3">
    <SectionTitle
      title="Operator toolbar"
      subtitle="Filter, snapshot, and inspect runtime output from one compact control band."
    />
    <div class="card preset-tonal-surface overflow-hidden">
      <div class="flex flex-col gap-4 border-b border-surface-200-800 p-4 sm:p-5 xl:flex-row xl:items-start xl:justify-between">
        <div class="space-y-1">
          <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Runtime stream</p>
          <p class="preset-typo-body-2 max-w-3xl text-surface-900-50">
            Placeholder controls mirror the future operator workflow without changing backend behavior.
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="badge preset-tonal-surface border-0">Newest 200 entries</span>
          <span class="badge preset-tonal-primary border-0">Auto-refresh placeholder</span>
          <span class="badge preset-tonal-surface border-0">Local-only access</span>
        </div>
      </div>

      <div class="grid gap-4 p-4 sm:p-5 xl:grid-cols-[minmax(0,1.25fr)_auto] xl:items-end">
        <div class="grid gap-3 md:grid-cols-3">
          <label class="space-y-1 text-sm font-medium text-surface-700-300">
            Level
            <select class="select select-sm" disabled>
              <option selected>All levels</option>
            </select>
          </label>
          <label class="space-y-1 text-sm font-medium text-surface-700-300">
            Search
            <input class="input input-sm" placeholder="Filter by text" disabled />
          </label>
          <label class="space-y-1 text-sm font-medium text-surface-700-300">
            Scope
            <select class="select select-sm" disabled>
              <option selected>All channels</option>
            </select>
          </label>
        </div>

        <div class="flex flex-wrap items-center gap-2 xl:justify-end">
          <button class="btn btn-sm preset-filled-primary-500" type="button" disabled>Refresh</button>
          <button class="btn btn-sm preset-tonal-surface" type="button" disabled>Download</button>
          <button class="btn btn-sm preset-outlined-surface-500" type="button" disabled>Clear</button>
        </div>
      </div>
    </div>
  </section>

  <section class="space-y-3">
    <SectionTitle
      title="Workspace preview"
      subtitle="Validate loading, empty, and failure states inside a more realistic operator layout."
    />

    <div class="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(18rem,0.85fr)]">
      <article class="card preset-tonal-surface overflow-hidden">
        <div class="flex flex-col gap-3 border-b border-surface-200-800 p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
          <div class="space-y-1">
            <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Stream panel</p>
            <p class="preset-typo-body-2 text-surface-900-50">Recent runtime output, grouping, and pagination previews.</p>
          </div>

          <div class="flex flex-wrap gap-2">
            {#each stateOptions as option}
              <button
                class={`btn btn-sm ${placeholderState === option.value
                  ? "preset-filled-primary-500"
                  : "preset-tonal-surface"}`}
                type="button"
                aria-pressed={placeholderState === option.value}
                on:click={() => {
                  placeholderState = option.value
                }}
              >
                {option.label}
              </button>
            {/each}
          </div>
        </div>

        <div class="space-y-4 p-4 sm:p-5">
          {#if placeholderState === "loading"}
            <div class="space-y-3">
              <div class="card preset-filled-surface-50-950 flex items-center justify-between gap-3 p-3">
                <div class="space-y-2">
                  <div class="skeleton h-3 w-28"></div>
                  <div class="skeleton h-4 w-40"></div>
                </div>
                <div class="skeleton h-6 w-24"></div>
              </div>
              <div class="card preset-filled-surface-50-950 space-y-3 p-4">
                <div class="skeleton h-4 w-56"></div>
                <div class="skeleton h-4 w-48"></div>
                <div class="skeleton h-4 w-64"></div>
                <div class="skeleton h-4 w-52"></div>
              </div>
              <p class="preset-typo-body-2 text-surface-700-300">Loading recent log entries...</p>
            </div>
          {:else if placeholderState === "empty"}
            <div class="card preset-tonal-primary space-y-3 p-6 text-center">
              <p class="preset-typo-title font-semibold text-surface-900-50">No log entries yet.</p>
              <p class="mx-auto max-w-xl text-surface-700-300">
                Newest 200 entries with older pagination controls will appear here once the dashboard receives runtime output.
              </p>
            </div>
          {:else}
            <div class="alert preset-tonal-error border-0" role="alert" aria-live="assertive">
              <p>Could not load logs preview. Check dashboard connectivity and try again.</p>
            </div>
          {/if}
        </div>
      </article>

      <div class="grid gap-4 content-start">
        <article class="card preset-tonal-surface space-y-4 p-4 sm:p-5">
          <div class="space-y-1">
            <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Queue health</p>
            <p class="preset-typo-body-2 text-surface-900-50">Supporting context for the active log view.</p>
          </div>
          <div class="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
            <div class="card preset-filled-surface-50-950 space-y-1 p-3">
              <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Buffered</p>
              <p class="text-xl font-semibold text-surface-900-50">0</p>
            </div>
            <div class="card preset-filled-surface-50-950 space-y-1 p-3">
              <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Dropped</p>
              <p class="text-xl font-semibold text-surface-900-50">0</p>
            </div>
            <div class="card preset-filled-surface-50-950 space-y-1 p-3">
              <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Source</p>
              <p class="text-xl font-semibold text-surface-900-50">local</p>
            </div>
          </div>
        </article>

        <article class="card preset-tonal-surface space-y-3 p-4 sm:p-5">
          <div class="space-y-1">
            <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Inspector notes</p>
            <p class="preset-typo-body-2 text-surface-700-300">
              Severity grouping, source metadata, and export actions stay intentionally read-only for now.
            </p>
          </div>
          <div class="card preset-filled-surface-50-950 p-4">
            <p class="preset-typo-body-2 text-surface-700-300">
              Future detail panes can dock here without changing the current placeholder semantics.
            </p>
          </div>
        </article>
      </div>
    </div>
  </section>
</PageShell>
