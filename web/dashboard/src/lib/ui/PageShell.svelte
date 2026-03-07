<script lang="ts">
  export let title = ""
</script>

<section class="space-y-6">
  {#if title}
    <header class="card preset-tonal-primary space-y-2 p-5 sm:p-6">
      <p class="preset-typo-caption uppercase tracking-[0.24em] text-primary-700-300">Dashboard</p>
      <h1 class="preset-typo-headline font-semibold text-surface-900-50">{title}</h1>
    </header>
  {/if}
  <div class="space-y-4">
    <slot />
  </div>
</section>
