import { afterEach, describe, expect, it, vi } from "vitest"

import {
  DEFAULT_THEME,
  createSystemThemeObserver,
  normalizeTheme,
  readSystemPrefersDark,
  readStoredTheme,
  resolveAppliedTheme,
  writeStoredTheme
} from "./theme"

describe("theme", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("defaults to system", () => {
    expect(DEFAULT_THEME).toBe("system")
  })

  it("normalizes invalid values to system", () => {
    expect(normalizeTheme("invalid")).toBe("system")
  })

  it("resolves system using prefers dark", () => {
    expect(resolveAppliedTheme("system", true)).toBe("dark")
    expect(resolveAppliedTheme("system", false)).toBe("light")
  })

  it("falls back to system for invalid stored value", () => {
    expect(readStoredTheme(() => "broken")).toBe("system")
  })

  it("falls back to default theme when storage read throws", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: () => {
          throw new Error("storage unavailable")
        }
      }
    })

    expect(readStoredTheme()).toBe("system")
  })

  it("reads system dark preference from matchMedia", () => {
    vi.stubGlobal("window", {
      matchMedia: () =>
        ({
          matches: true,
          media: "(prefers-color-scheme: dark)",
          onchange: null,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          dispatchEvent: () => true
        })
    })

    expect(readSystemPrefersDark()).toBe(true)
  })

  it("persists selected theme", () => {
    let stored = ""
    writeStoredTheme("dark", (value) => {
      stored = value
    })
    expect(stored).toBe("dark")
  })

  it("ignores storage write errors", () => {
    vi.stubGlobal("window", {
      localStorage: {
        setItem: () => {
          throw new Error("storage unavailable")
        }
      }
    })

    expect(() => writeStoredTheme("dark")).not.toThrow()
  })

  it("wires system theme observer subscription", () => {
    const callbacks: Array<(prefersDark: boolean) => void> = []
    let unsubscribed = false

    const unsubscribe = createSystemThemeObserver(
      (callback) => {
        callbacks.push(callback)
        return () => {
          unsubscribed = true
        }
      },
      () => undefined
    )

    expect(callbacks).toHaveLength(1)
    unsubscribe()
    expect(unsubscribed).toBe(true)
  })

  it("subscribes with legacy media query listeners", () => {
    let listener: ((event: { matches: boolean }) => void) | undefined
    let removedListener: ((event: { matches: boolean }) => void) | undefined

    vi.stubGlobal("window", {
      matchMedia: () =>
        ({
          matches: false,
          media: "(prefers-color-scheme: dark)",
          onchange: null,
          addListener(callback: (event: { matches: boolean }) => void): void {
            listener = callback
          },
          removeListener(callback: (event: { matches: boolean }) => void): void {
            removedListener = callback
          },
          dispatchEvent: () => true
        })
    })

    let observedPrefersDark: boolean | undefined
    const unsubscribe = createSystemThemeObserver(undefined, (prefersDark) => {
      observedPrefersDark = prefersDark
    })

    listener?.({ matches: true })
    expect(observedPrefersDark).toBe(true)

    unsubscribe()
    expect(removedListener).toBe(listener)
  })

  it("subscribes with modern media query listeners", () => {
    let listener: ((event: { matches: boolean }) => void) | undefined
    let removedListener: ((event: { matches: boolean }) => void) | undefined

    vi.stubGlobal("window", {
      matchMedia: () =>
        ({
          matches: false,
          media: "(prefers-color-scheme: dark)",
          onchange: null,
          addEventListener: (
            eventName: string,
            callback: (event: { matches: boolean }) => void
          ): void => {
            if (eventName === "change") {
              listener = callback
            }
          },
          removeEventListener: (
            eventName: string,
            callback: (event: { matches: boolean }) => void
          ): void => {
            if (eventName === "change") {
              removedListener = callback
            }
          },
          dispatchEvent: () => true
        })
    })

    let observedPrefersDark: boolean | undefined
    const unsubscribe = createSystemThemeObserver(undefined, (prefersDark) => {
      observedPrefersDark = prefersDark
    })

    listener?.({ matches: true })
    expect(observedPrefersDark).toBe(true)

    unsubscribe()
    expect(removedListener).toBe(listener)
  })
})
