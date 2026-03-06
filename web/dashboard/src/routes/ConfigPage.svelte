<script lang="ts">
  import PageShell from "../lib/ui/PageShell.svelte"
  import SectionTitle from "../lib/ui/SectionTitle.svelte"

  const showRestartBanner = true
</script>

<PageShell title="Config">
  {#if showRestartBanner}
    <div class="alert preset-tonal-warning border-0">
      <p>
        Restart required placeholder: some configuration updates take effect after restarting squidbot.
      </p>
    </div>
  {/if}

  <section class="space-y-3">
    <SectionTitle
      title="Runtime Settings"
      subtitle="Grouped controls for update intervals and log handling behavior."
    />
    <div class="grid gap-3 lg:grid-cols-2">
      <article class="card preset-tonal-surface space-y-3 p-5 shadow-sm">
        <h3 class="preset-typo-title font-semibold text-surface-900-50">Dashboard Polling</h3>
        <label class="space-y-1 text-sm font-medium text-surface-700-300">
          Refresh cadence
          <select class="select select-sm" disabled>
            <option selected>Adaptive (default)</option>
          </select>
        </label>
        <p class="preset-typo-body-2 text-surface-700-300">Will map to existing polling logic without API changes.</p>
      </article>

      <article class="card preset-tonal-surface space-y-3 p-5 shadow-sm">
        <h3 class="preset-typo-title font-semibold text-surface-900-50">Log Retention</h3>
        <label class="space-y-1 text-sm font-medium text-surface-700-300">
          Entries shown in dashboard
          <input class="input input-sm" value="200" disabled />
        </label>
        <p class="preset-typo-body-2 text-surface-700-300">
          Read-only placeholder for current fixed retention behavior.
        </p>
      </article>
    </div>
  </section>

  <section class="space-y-3">
    <SectionTitle
      title="Channel Configuration"
      subtitle="Section grouping preview for channel-specific toggles and credentials status."
    />
    <article class="card preset-tonal-primary space-y-4 p-5">
      <label class="flex items-center justify-between gap-3 text-sm font-medium text-surface-900-50">
        Matrix channel enabled
        <input type="checkbox" class="checkbox" disabled />
      </label>
      <label class="flex items-center justify-between gap-3 text-sm font-medium text-surface-900-50">
        Email channel enabled
        <input type="checkbox" class="checkbox" disabled />
      </label>
      <p class="preset-typo-body-2 text-surface-700-300">Credentials editing remains intentionally out of scope.</p>
    </article>
  </section>

  <section class="space-y-3">
    <SectionTitle
      title="Apply Changes"
      subtitle="Primary action for save, secondary actions for safe local resets."
    />
    <div class="card preset-tonal-surface p-5">
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
      <p class="preset-typo-body-2 mt-3 text-surface-700-300">
        Actions are placeholders only while backend config mutation endpoints remain disabled.
      </p>
    </div>
  </section>
</PageShell>
