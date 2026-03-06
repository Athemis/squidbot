<script lang="ts">
  type StatusTone = "ok" | "warn" | "error" | "idle"

  export let tone: StatusTone = "idle"
  export let label: string

  const toneClass: Record<StatusTone, string> = {
    ok: "variant-soft-success",
    warn: "variant-soft-warning",
    error: "variant-soft-error",
    idle: "variant-soft-surface"
  }
</script>

<span class={`badge ${toneClass[tone]}`}>{label}</span>
