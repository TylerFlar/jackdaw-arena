import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ReplayFrame } from "../../api/client";
import fixtures from "../../replay/fixtures.json";
import { beatenBlind, RoundEval } from "./Screens";

// A real round's end (src/replay/fixtures.json): the run's blind is cleared by then ("?").
const end = (fixtures as unknown as Record<string, [ReplayFrame, ReplayFrame]>).cash_out![0];

describe("the round's end", () => {
  it("names the blind just beaten from the blind row", () => {
    expect(end.phase).toBe("round_eval");
    expect(end.blind?.key).toBe("");
    expect(beatenBlind(end)).toBe("Small Blind");
    expect(beatenBlind({ ...end, blind: null })).toBe("Small Blind");
    // After the boss, the whole row is defeated: the boss is the one just beaten.
    const row = end.blinds!;
    const all = { small: row.small!, big: { ...row.big!, status: "DEFEATED" }, boss: { ...row.boss!, status: "DEFEATED" } };
    expect(beatenBlind({ ...end, blinds: all })).toBe(row.boss!.name);
  });

  it("says so on the screen, with what cashing out pays", () => {
    render(<RoundEval frame={end} />);
    expect(screen.getByRole("heading", { name: "Small Blind defeated" })).toBeInTheDocument();
    expect(screen.getByText(`Cash out $${end.outcome!.cash_out}`)).toBeInTheDocument();
  });
});
