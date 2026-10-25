import { describe, expect, it } from "vitest";
import { niceTicks, roundedTop } from "../components/Histogram";
import { ago, endReason, interval, num, pct } from "./format";

describe("format", () => {
  it("shows game numbers, including overflowed scores", () => {
    expect(num(1234)).toBe("1,234");
    expect(num(2.5e7)).toBe("25M");
    expect(num("inf")).toBe("∞");
    expect(num(null)).toBe("-");
  });
  it("formats intervals and percentages", () => {
    expect(interval([4.27, 4.77])).toBe("4.27 – 4.77");
    expect(interval([0, 0.0076], 1, true)).toBe("0.0% – 0.8%");
    expect(interval(null)).toBe("-");
    expect(pct(0.123)).toBe("12.3%");
  });
  it("says how episodes ended", () => {
    expect(endReason("idle")).toBe("timed out");
    expect(endReason("refused")).toContain("env bug");
  });
  it("says when, relatively", () => {
    const now = Date.parse("2026-10-24T12:00:00Z");
    expect(ago("2026-10-24T11:00:00Z", now)).toBe("1 hour ago");
    expect(ago("2026-10-24T11:59:50Z", now)).toBe("just now");
  });
});

describe("chart geometry", () => {
  it("picks clean ticks that cover the maximum", () => {
    expect(niceTicks(7)).toEqual([0, 2, 4, 6, 8]);
    expect(niceTicks(130)).toEqual([0, 50, 100, 150]);
    expect(niceTicks(1)).toEqual([0, 0.5, 1]);
  });
  it("rounds only a column's top corners", () => {
    const d = roundedTop(10, 20, 24, 50, 4);
    expect(d.startsWith("M10,70L10,24Q10,20 14,20")).toBe(true);
    expect(d.endsWith("L34,70Z")).toBe(true);
    expect(roundedTop(0, 0, 24, 2, 4)).toContain("L0,2Q0,0 2,0"); // a short column keeps its shape
  });
});
