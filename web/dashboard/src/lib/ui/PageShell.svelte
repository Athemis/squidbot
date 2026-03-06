<script lang="ts">
  export let title = ""
</script>

<section class="space-y-6 rounded-xl border border-surface-200-700 bg-surface-50-950 p-6">
  {#if title}
    <h1 class="text-2xl font-semibold tracking-tight text-surface-900-50">{title}</h1>
  {/if}
  <div class="space-y-4">
    <slot />
  </div>
</section>
