<script lang="ts">
  export let label: string
  export let value: string | number
  export let detail = ""
</script>

<article class="card preset-tonal-surface space-y-3 p-5 shadow-sm">
  <p class="preset-typo-caption uppercase tracking-[0.2em] text-surface-700-300">{label}</p>
  <p class="text-3xl font-semibold tracking-tight break-words text-surface-900-50">{value}</p>
  {#if detail}
    <p class="preset-typo-body-2 text-surface-700-300">{detail}</p>
  {/if}
</article>
