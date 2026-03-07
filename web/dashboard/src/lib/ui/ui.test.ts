import { describe, expect, it } from "vitest"

import appSource from "../../App.svelte?raw"
import chatPageSource from "../../routes/ChatPage.svelte?raw"
import configPageSource from "../../routes/ConfigPage.svelte?raw"
import logsPageSource from "../../routes/LogsPage.svelte?raw"
import overviewPageSource from "../../routes/OverviewPage.svelte?raw"
import pageShellSource from "./PageShell.svelte?raw"
import sectionTitleSource from "./SectionTitle.svelte?raw"

describe("ui primitives", () => {
  it("exports named primitives from index", async () => {
    const module = await import("./index")

    expect(module.PageShell).toBeDefined()
    expect(module.MetricCard).toBeDefined()
    expect(module.StatusChip).toBeDefined()
    expect(module.SectionTitle).toBeDefined()
  })

  it("renders page and section headings with a clear hierarchy", () => {
    expect(appSource).not.toMatch(/<h1\b/)
    expect(pageShellSource).toMatch(/<h1\b/)
    expect(sectionTitleSource).toMatch(/<h2\b/)
  })

  it("keeps the app shell mostly in stock Skeleton/Tailwind markup", () => {
    expect(appSource).not.toContain("dashboard-shell__topbar")
    expect(appSource).not.toContain("dashboard-shell__tabs")
    expect(appSource).not.toContain("dashboard-shell__theme-select-wrap")
    expect(appSource).toContain('role="tablist"')
    expect(appSource).toContain('role="tab"')
    expect(appSource).toContain('role="tabpanel"')
    expect(appSource).toContain("ArrowRight")
    expect(appSource).toContain("Home")
  })

  it("marks visible dashboard alerts as live alert regions", () => {
    expect(configPageSource).not.toContain('role="alert"')
    expect(configPageSource).toContain("Restart required placeholder")
    expect(logsPageSource).toContain('role="alert"')
    expect(logsPageSource).toContain('aria-pressed={placeholderState === option.value}')
    expect(logsPageSource).toContain("Could not load logs preview")
    expect(overviewPageSource).toContain('role="alert"')
    expect(chatPageSource).toContain('role="alert"')
  })

  it("gives overview data tables accessible captions", () => {
    expect(overviewPageSource).toContain("Channel health and runtime errors")
    expect(overviewPageSource).toContain("Recent inbound session activity")
    expect(overviewPageSource).toMatch(/<caption[^>]*class=\"sr-only\"/)
  })

  it("keeps transcript content outside the live status region", () => {
    expect(chatPageSource).toContain('role="status"')
    expect(chatPageSource).toContain('aria-live="polite"')
    expect(chatPageSource).toContain("Ready to send.")
    expect(chatPageSource).toContain("Response complete")
    expect(chatPageSource).not.toContain('min-h-56 p-4" aria-live="polite"')
  })
})
