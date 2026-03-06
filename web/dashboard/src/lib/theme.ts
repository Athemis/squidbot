export type Theme = "system" | "light" | "dark"

export const DEFAULT_THEME: Theme = "system"

const THEME_STORAGE_KEY = "squidbot-dashboard-theme"
const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)"

type ThemeReader = () => string | null | undefined
type ThemeWriter = (value: Theme) => void
type SystemThemeSubscriber = (callback: (prefersDark: boolean) => void) => () => void

export function normalizeTheme(value: unknown): Theme {
  if (value === "system" || value === "light" || value === "dark") {
    return value
  }

  return DEFAULT_THEME
}

export function resolveAppliedTheme(theme: Theme, prefersDark: boolean): "light" | "dark" {
  if (theme === "system") {
    return prefersDark ? "dark" : "light"
  }

  return theme
}

export function readStoredTheme(readTheme?: ThemeReader): Theme {
  if (readTheme) {
    return normalizeTheme(readTheme())
  }

  if (typeof window === "undefined") {
    return DEFAULT_THEME
  }

  try {
    return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    return DEFAULT_THEME
  }
}

export function writeStoredTheme(theme: Theme, writeTheme?: ThemeWriter): void {
  if (writeTheme) {
    writeTheme(theme)
    return
  }

  if (typeof window === "undefined") {
    return
  }

  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    return
  }
}

export function readSystemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false
  }

  return window.matchMedia(DARK_SCHEME_QUERY).matches
}

function subscribeToSystemTheme(callback: (prefersDark: boolean) => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => undefined
  }

  const mediaQueryList = window.matchMedia(DARK_SCHEME_QUERY)
  const listener = (event: MediaQueryListEvent) => {
    callback(event.matches)
  }

  if (typeof mediaQueryList.addEventListener === "function") {
    mediaQueryList.addEventListener("change", listener)

    return () => {
      mediaQueryList.removeEventListener("change", listener)
    }
  }

  if (typeof mediaQueryList.addListener === "function") {
    mediaQueryList.addListener(listener)

    return () => {
      mediaQueryList.removeListener(listener)
    }
  }

  return () => undefined
}

export function createSystemThemeObserver(
  subscribe: SystemThemeSubscriber = subscribeToSystemTheme,
  onChange: (prefersDark: boolean) => void
): () => void {
  return subscribe(onChange)
}
