import { describe, expect, it } from "vitest";

import { durationLabel, relativeTime, shortId, usd } from "@/lib/format";

describe("format helpers", () => {
  it("shortId truncates ULID-style ids", () => {
    expect(shortId("sess_01HBCD0XYZABCDEFGHJKMNPQRS")).toBe("01HBCD0X…");
    expect(shortId("short")).toBe("short");
  });

  it("relativeTime returns dash for missing input", () => {
    expect(relativeTime(null)).toBe("—");
    expect(relativeTime(undefined)).toBe("—");
    expect(relativeTime("not-a-date")).toBe("—");
  });

  it("relativeTime renders a suffix for valid dates", () => {
    const out = relativeTime(new Date(Date.now() - 30_000));
    expect(out).toMatch(/ago$/);
  });

  it("durationLabel compresses to h/m/s", () => {
    expect(durationLabel(null)).toBe("—");
    expect(durationLabel(0)).toBe("<1s");
    expect(durationLabel(45)).toBe("45s");
    expect(durationLabel(125)).toBe("2m 5s");
    expect(durationLabel(3725)).toBe("1h 2m 5s");
  });

  it("usd formats with currency symbol", () => {
    expect(usd(null)).toBe("—");
    expect(usd(1.2345)).toBe("$1.23");
    expect(usd(0.0042)).toBe("$0.0042");
  });
});
