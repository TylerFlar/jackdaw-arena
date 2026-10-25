import type { CardModel } from "../api/client";
import type { AtlasName } from "./art";

/** A cell of an atlas: x is the column, y the row. */
export type Cell = { atlas: AtlasName; x: number; y: number };
type Pos = number[] | null | undefined;
type Info = { set?: string | null; pos?: Pos; soul?: Pos } | undefined;

/** How a card is drawn: layers bottom to top, a floating layer, and a size for the few cards
 * the game draws smaller. */
export type CardArt = { layers: Cell[]; soul?: Cell; scale?: number };

const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"];
const SUITS = ["H", "C", "D", "S"];

// Sprites the game places by hand rather than through its data (game.lua, shared sprites).
const SEALS: Record<string, [number, number]> = { Gold: [2, 0], Purple: [4, 4], Red: [5, 4], Blue: [6, 4] };
const DEBUFF: Cell = { atlas: "centers", x: 4, y: 0 };
const STICKERS = { eternal: [0, 0], perishable: [0, 2], rental: [1, 2] } as const;
const SOUL: Cell = { atlas: "centers", x: 0, y: 1 }; // The Soul's floating gem

const ATLAS_OF_SET: Record<string, AtlasName> = {
  Joker: "jokers",
  Tarot: "tarots",
  Planet: "tarots",
  Spectral: "tarots",
  Voucher: "vouchers",
  Booster: "boosters",
  Back: "centers",
  Enhanced: "centers",
  Default: "centers",
};

const cell = (atlas: AtlasName, pos: Pos): Cell | null =>
  pos && pos.length === 2 ? { atlas, x: pos[0]!, y: pos[1]! } : null;

/** A playing card's face: "D_A" is the ace of diamonds. */
export function frontCell(front: string | null | undefined): Cell | null {
  const [suit, rank] = (front ?? "").split("_");
  const x = RANKS.indexOf(rank ?? ""), y = SUITS.indexOf(suit ?? ""); // prettier-ignore
  return x < 0 || y < 0 ? null : { atlas: "cards", x, y };
}

/** The layers for a card, or null when a position is unknown (then the plain card is drawn). */
export function cardArt(card: CardModel, info: (key: string) => Info, back: string): CardArt | null {
  if (card.face_down) {
    const b = cell("centers", info(back)?.pos);
    return b ? { layers: [b] } : null;
  }
  const key = card.key ?? "c_base";
  const center = info(key);
  const atlas = ATLAS_OF_SET[center?.set ?? (card.front ? "Enhanced" : "")];
  const base = atlas ? cell(atlas, center?.pos) : null;
  if (!base) return null;
  const layers = [base];
  if (card.front && key !== "m_stone") {
    const face = frontCell(card.front);
    if (!face) return null;
    layers.push(face);
  }
  const seal = card.seal ? SEALS[card.seal] : undefined;
  if (seal) layers.push({ atlas: "centers", x: seal[0], y: seal[1] });
  for (const s of ["eternal", "perishable", "rental"] as const) {
    if (card[s]) layers.push({ atlas: "stickers", x: STICKERS[s][0], y: STICKERS[s][1] });
  }
  if (card.debuff) layers.push(DEBUFF);
  const soul = key === "c_soul" ? SOUL : (cell("jokers", center?.soul) ?? undefined);
  return { layers, soul, scale: key === "j_wee" ? 0.7 : undefined };
}

/** The atlas a catalog table's sprites live in. */
export function tableCell(atlas: "tags" | "stakes" | "blinds", pos: Pos): Cell | null {
  return cell(atlas, pos);
}
