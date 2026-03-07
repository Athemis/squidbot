<script lang="ts">
  export let label: string
  export let value: string | number
  export let detail = ""
</script>

<article class="card preset-tonal-surface flex h-full flex-col gap-3 p-4 sm:p-5">
  <div class="flex items-start justify-between gap-3">
    <p class="preset-typo-caption uppercase tracking-[0.18em] text-surface-700-300">{label}</p>
    {#if detail}
      <span class="badge preset-tonal-surface border-0 shrink-0">{detail}</span>
    {/if}
  </div>
  <p class="break-words text-2xl font-semibold tracking-tight text-surface-900-50 sm:text-3xl">{value}</p>
</article>
