<script lang="ts">
  export let title: string
  export let subtitle = ""
</script>

<header class="space-y-1">
  <h2 class="text-lg font-semibold tracking-tight text-surface-900-50">{title}</h2>
  {#if subtitle}
    <p class="text-sm text-surface-700-300">{subtitle}</p>
  {/if}
</header>
