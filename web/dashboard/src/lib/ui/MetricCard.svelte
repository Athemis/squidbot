<script lang="ts">
  export let label: string
  export let value: string | number
  export let detail = ""
</script>

<article class="card space-y-2 border border-surface-200-700 bg-surface-100-900 p-4">
  <p class="text-sm font-medium text-surface-700-300">{label}</p>
  <p class="text-3xl font-semibold text-surface-900-50">{value}</p>
  {#if detail}
    <p class="text-xs text-surface-700-300">{detail}</p>
  {/if}
</article>
