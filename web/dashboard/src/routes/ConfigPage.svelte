<script lang="ts">
  import PageShell from "../lib/ui/PageShell.svelte"
  import SectionTitle from "../lib/ui/SectionTitle.svelte"

  const showRestartBanner = true
</script>

<PageShell title="Config">
  {#if showRestartBanner}
    <div class="alert preset-tonal-warning border-0">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <p>
          Restart required placeholder: some configuration updates take effect after restarting squidbot.
        </p>
        <span class="badge preset-tonal-surface border-0">Applies after save</span>
      </div>
    </div>
  {/if}

  <section class="space-y-3">
    <SectionTitle
      title="Runtime controls"
      subtitle="Operator-facing settings stay grouped by scope so placeholders read like a real control surface."
    />
    <div class="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,0.9fr)]">
      <article class="card preset-tonal-surface overflow-hidden">
        <div class="flex flex-col gap-4 border-b border-surface-200-800 p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
          <div class="space-y-1">
            <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Core runtime</p>
            <p class="preset-typo-body-2 max-w-3xl text-surface-900-50">
              Default polling and log visibility remain unchanged while the grouped layout becomes easier to scan.
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <span class="badge preset-tonal-primary border-0">Read-only preview</span>
            <span class="badge preset-tonal-surface border-0">No API mutations</span>
          </div>
        </div>

        <div class="grid gap-4 p-4 sm:p-5 lg:grid-cols-2">
          <article class="card preset-filled-surface-50-950 space-y-3 p-4">
            <h3 class="preset-typo-title font-semibold text-surface-900-50">Dashboard polling</h3>
            <label class="space-y-1 text-sm font-medium text-surface-700-300">
              Refresh cadence
              <select class="select select-sm" disabled>
                <option selected>Adaptive (default)</option>
              </select>
            </label>
            <p class="preset-typo-body-2 text-surface-700-300">
              Will map to existing polling logic without API changes.
            </p>
          </article>

          <article class="card preset-filled-surface-50-950 space-y-3 p-4">
            <h3 class="preset-typo-title font-semibold text-surface-900-50">Log retention</h3>
            <label class="space-y-1 text-sm font-medium text-surface-700-300">
              Entries shown in dashboard
              <input class="input input-sm" value="200" disabled />
            </label>
            <p class="preset-typo-body-2 text-surface-700-300">
              Read-only placeholder for current fixed retention behavior.
            </p>
          </article>
        </div>
      </article>

      <article class="card preset-tonal-surface space-y-4 p-4 sm:p-5">
        <div class="space-y-1">
          <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Change policy</p>
          <p class="preset-typo-body-2 text-surface-700-300">
            Advisory state keeps operators aware of save and restart boundaries.
          </p>
        </div>
        <div class="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
          <div class="card preset-filled-surface-50-950 space-y-1 p-3">
            <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Draft mode</p>
            <p class="text-xl font-semibold text-surface-900-50">On</p>
          </div>
          <div class="card preset-filled-surface-50-950 space-y-1 p-3">
            <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Restart</p>
            <p class="text-xl font-semibold text-surface-900-50">Manual</p>
          </div>
          <div class="card preset-filled-surface-50-950 space-y-1 p-3">
            <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Source</p>
            <p class="text-xl font-semibold text-surface-900-50">Disk</p>
          </div>
        </div>
      </article>
    </div>
  </section>

  <section class="space-y-3">
    <SectionTitle
      title="Channel groups"
      subtitle="Separate channel enablement, credential posture, and connection notes into believable operator panels."
    />
    <div class="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
      <article class="card preset-tonal-primary space-y-4 p-4 sm:p-5">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="preset-typo-title font-semibold text-surface-900-50">Transport enablement</h3>
          <span class="badge preset-tonal-surface border-0">Preview only</span>
        </div>

        <div class="grid gap-3">
          <label class="card preset-filled-surface-50-950 flex items-center justify-between gap-3 p-3 text-sm font-medium text-surface-900-50">
            <div class="space-y-1">
              <span class="block">Matrix channel enabled</span>
              <span class="preset-typo-body-2 text-surface-700-300">Primary real-time room adapter.</span>
            </div>
            <input type="checkbox" class="checkbox" disabled />
          </label>

          <label class="card preset-filled-surface-50-950 flex items-center justify-between gap-3 p-3 text-sm font-medium text-surface-900-50">
            <div class="space-y-1">
              <span class="block">Email channel enabled</span>
              <span class="preset-typo-body-2 text-surface-700-300">Batch-oriented inbound and outbound handling.</span>
            </div>
            <input type="checkbox" class="checkbox" disabled />
          </label>
        </div>
      </article>

      <article class="card preset-tonal-surface space-y-4 p-4 sm:p-5">
        <div class="space-y-1">
          <h3 class="preset-typo-title font-semibold text-surface-900-50">Credentials status</h3>
          <p class="preset-typo-body-2 text-surface-700-300">
            Credentials editing remains intentionally out of scope.
          </p>
        </div>

        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
          <div class="card preset-filled-surface-50-950 space-y-1 p-3">
            <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Matrix</p>
            <p class="text-base font-semibold text-surface-900-50">Stored outside dashboard</p>
          </div>
          <div class="card preset-filled-surface-50-950 space-y-1 p-3">
            <p class="preset-typo-caption uppercase tracking-[0.16em] text-surface-700-300">Email</p>
            <p class="text-base font-semibold text-surface-900-50">Stored outside dashboard</p>
          </div>
        </div>
      </article>
    </div>
  </section>

  <section class="space-y-3">
    <SectionTitle
      title="Apply changes"
      subtitle="Action grouping keeps save, revert, and reload controls aligned with the rest of the dashboard suite."
    />
    <div class="card preset-tonal-surface overflow-hidden">
      <div class="flex flex-col gap-4 border-b border-surface-200-800 p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
        <div class="space-y-1">
          <p class="preset-typo-caption uppercase tracking-[0.24em] text-surface-700-300">Draft actions</p>
          <p class="preset-typo-body-2 max-w-3xl text-surface-900-50">
            Actions remain placeholders only while backend config mutation endpoints stay disabled.
          </p>
        </div>
        <span class="badge preset-tonal-surface border-0">Safe local resets only</span>
      </div>

      <div class="grid gap-4 p-4 sm:p-5 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,0.7fr)]">
        <div class="flex flex-wrap gap-2">
          <button class="btn btn-sm preset-filled-primary-500" type="button" disabled>
            Save changes
          </button>
          <button class="btn btn-sm preset-tonal-surface" type="button" disabled>
            Revert draft
          </button>
          <button class="btn btn-sm preset-outlined-surface-500" type="button" disabled>
            Reload from disk
          </button>
        </div>

        <div class="card preset-filled-surface-50-950 p-4">
          <p class="preset-typo-body-2 text-surface-700-300">
            The current redesign improves grouping only. Save behavior, restart expectations, and backend constraints stay exactly as they are today.
          </p>
        </div>
      </div>
    </div>
  </section>
</PageShell>
