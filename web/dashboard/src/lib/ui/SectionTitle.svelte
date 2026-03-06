<script lang="ts">
  export let title: string
  export let subtitle = ""
</script>

<header class="space-y-2">
  <h2 class="preset-typo-title font-semibold text-surface-900-50">{title}</h2>
  {#if subtitle}
    <p class="preset-typo-body-2 max-w-3xl text-surface-700-300">{subtitle}</p>
  {/if}
</header>
