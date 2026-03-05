import { describe, expect, it } from "vitest"

import { choosePollingIntervalMs } from "./polling"

describe("choosePollingIntervalMs", () => {
  it("uses 2s polling for visible tabs", () => {
    expect(choosePollingIntervalMs("visible")).toBe(2000)
  })

  it("uses 15s polling for hidden tabs", () => {
    expect(choosePollingIntervalMs("hidden")).toBe(15000)
  })

  it("falls back safely when document is unavailable", () => {
    expect(choosePollingIntervalMs()).toBe(15000)
  })
})
