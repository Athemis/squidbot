export function choosePollingIntervalMs(
  visibilityState?: DocumentVisibilityState
): number {
  const fallbackState =
    typeof document !== "undefined" ? document.visibilityState : "hidden"
  const effectiveState = visibilityState ?? fallbackState
  return effectiveState === "visible" ? 2000 : 15000
}
