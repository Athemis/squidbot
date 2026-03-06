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
      title="Toolbar"
      subtitle="Preview log filters and actions with clear visual hierarchy."
    />
    <div class="card preset-tonal-surface space-y-4 p-5">
      <div class="grid gap-3 lg:grid-cols-[1fr_auto] lg:items-end">
        <div class="grid gap-3 sm:grid-cols-2">
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
        </div>

        <div class="flex flex-wrap items-center gap-2 lg:justify-end">
          <button class="btn btn-sm preset-filled-primary-500" type="button" disabled>Refresh</button>
          <button class="btn btn-sm preset-tonal-surface" type="button" disabled>Download</button>
          <button class="btn btn-sm preset-outlined-surface-500" type="button" disabled>Clear</button>
        </div>
      </div>
      <p class="preset-typo-body-2 text-surface-700-300">
        Toolbar controls are visual placeholders only. Live log interactions arrive in a later task.
      </p>
    </div>
  </section>

  <section class="space-y-3">
    <SectionTitle
      title="State placeholders"
      subtitle="Validate readability for loading, empty, and error views before wiring backend data."
    />

    <div class="flex flex-wrap gap-2">
      {#each stateOptions as option}
        <button
          class={`btn btn-sm ${placeholderState === option.value
            ? "preset-filled-primary-500"
            : "preset-tonal-surface"}`}
          type="button"
          on:click={() => {
            placeholderState = option.value
          }}
        >
          {option.label}
        </button>
      {/each}
    </div>

    {#if placeholderState === "loading"}
      <div class="card preset-tonal-surface space-y-3 p-5">
        <div class="skeleton h-4 w-56"></div>
        <div class="skeleton h-4 w-48"></div>
        <div class="skeleton h-4 w-64"></div>
        <p class="preset-typo-body-2 text-surface-700-300">Loading recent log entries...</p>
      </div>
    {:else if placeholderState === "empty"}
      <div class="card preset-tonal-primary p-6 text-center">
        <p class="preset-typo-title font-semibold text-surface-900-50">No log entries yet.</p>
        <p class="mt-2 text-surface-700-300">
          Newest 200 entries with older pagination controls will appear here.
        </p>
      </div>
    {:else}
      <div class="alert preset-tonal-error border-0" role="alert" aria-live="assertive">
        <p>Could not load logs preview. Check dashboard connectivity and try again.</p>
      </div>
    {/if}
  </section>
</PageShell>
