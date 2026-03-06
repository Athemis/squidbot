import { describe, expect, it } from "vitest"

describe("ui primitives", () => {
  it("exports named primitives from index", async () => {
    const module = await import("./index")

    expect(module.PageShell).toBeDefined()
    expect(module.MetricCard).toBeDefined()
    expect(module.StatusChip).toBeDefined()
    expect(module.SectionTitle).toBeDefined()
  })
})
