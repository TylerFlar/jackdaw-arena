import { describe, expect, it } from "vitest";
import type { CardModel } from "../api/client";
import { cardArt, frontCell } from "./cells";

const CATALOG: Record<string, { set: string; pos: number[]; soul?: number[] }> = {
  c_base: { set: "Default", pos: [1, 0] },
  m_glass: { set: "Enhanced", pos: [5, 1] },
  m_stone: { set: "Enhanced", pos: [5, 0] },
  b_red: { set: "Back", pos: [0, 0] },
  j_wee: { set: "Joker", pos: [0, 0] },
  j_caino: { set: "Joker", pos: [3, 8], soul: [3, 9] },
  c_soul: { set: "Spectral", pos: [2, 2] },
  p_arcana_normal_1: { set: "Booster", pos: [0, 0] },
};
const info = (key: string) => CATALOG[key];

const card = (over: Partial<CardModel>): CardModel => ({
  face_down: false, key: "c_base", front: "H_A", suit: "Hearts", rank: "Ace", edition: null,
  seal: null, debuff: false, cost: 1, sell_cost: 1, eternal: false, perishable: false,
  rental: false, ...over,
}); // prettier-ignore

describe("sprite cells", () => {
  it("places card faces on the deck's grid: ranks across, suits down", () => {
    expect(frontCell("H_2")).toEqual({ atlas: "cards", x: 0, y: 0 });
    expect(frontCell("D_A")).toEqual({ atlas: "cards", x: 12, y: 2 });
    expect(frontCell("S_T")).toEqual({ atlas: "cards", x: 8, y: 3 });
    expect(frontCell("X_9")).toBeNull();
    expect(frontCell(null)).toBeNull();
  });

  it("stacks a playing card's enhancement, face, seal and debuff", () => {
    const art = cardArt(card({ key: "m_glass", front: "C_K", seal: "Gold", debuff: true }), info, "b_red");
    expect(art?.layers).toEqual([
      { atlas: "centers", x: 5, y: 1 },
      { atlas: "cards", x: 11, y: 1 },
      { atlas: "centers", x: 2, y: 0 },
      { atlas: "centers", x: 4, y: 0 },
    ]);
  });

  it("draws no face on a Stone card", () => {
    expect(cardArt(card({ key: "m_stone" }), info, "b_red")?.layers).toEqual([{ atlas: "centers", x: 5, y: 0 }]);
  });

  it("shows the deck's back for a face-down card", () => {
    expect(cardArt(card({ face_down: true, key: null }), info, "b_red")).toEqual({
      layers: [{ atlas: "centers", x: 0, y: 0 }],
    });
  });

  it("floats a legendary's face and The Soul's gem, and shrinks Wee Joker", () => {
    const caino = cardArt(card({ key: "j_caino", front: null, rank: null, suit: null, eternal: true }), info, "b_red");
    expect(caino?.layers).toEqual([{ atlas: "jokers", x: 3, y: 8 }, { atlas: "stickers", x: 0, y: 0 }]);
    expect(caino?.soul).toEqual({ atlas: "jokers", x: 3, y: 9 });
    expect(cardArt(card({ key: "c_soul", front: null }), info, "b_red")?.soul).toEqual({ atlas: "centers", x: 0, y: 1 });
    expect(cardArt(card({ key: "j_wee", front: null }), info, "b_red")?.scale).toBe(0.7);
    expect(cardArt(card({ key: "p_arcana_normal_1", front: null }), info, "b_red")?.layers).toEqual([
      { atlas: "boosters", x: 0, y: 0 },
    ]);
  });

  it("gives up on keys it can't place, so the plain card is drawn", () => {
    expect(cardArt(card({ key: "j_unknown", front: null }), info, "b_red")).toBeNull();
    expect(cardArt(card({ front: "Q_Q" }), info, "b_red")).toBeNull();
  });
});
