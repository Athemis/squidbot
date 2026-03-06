<script lang="ts">
  type StatusTone = "ok" | "warn" | "error" | "idle"

  export let tone: StatusTone = "idle"
  export let label: string

  const toneClass: Record<StatusTone, string> = {
    ok: "preset-tonal-success",
    warn: "preset-tonal-warning",
    error: "preset-tonal-error",
    idle: "preset-tonal-surface"
  }
</script>

<span class={`badge ${toneClass[tone]} border-0 font-medium capitalize`}>{label}</span>
