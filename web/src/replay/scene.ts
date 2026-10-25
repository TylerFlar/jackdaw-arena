import type { ReplayCard, ReplayFrame } from "../api/client";

/** Game numbers arrive as numbers, or as "inf"/"-inf"/"nan" when a score overflows. */
export type Num = number | string;

/** The board's card areas. */
export const ZONES = ["jokers", "consumables", "play", "hand", "shop", "vouchers", "boosters", "pack"] as const;
export type Zone = (typeof ZONES)[number];

/** A card as the board draws it at one moment. */
export type Slot = {
  card: ReplayCard;
  /** Lifted: selected in hand, or a card that scores. */
  raised?: boolean;
  /** The card an event belongs to, or acts on: it pulses. */
  active?: boolean;
  /** On its way off the board: to the discard pile, or out of the run. Cards fade out in
   * the moment before they're gone, so a card is never drawn twice. */
  leaving?: "discard" | "shatter" | "dissolve";
  /** New to the board at this moment (drawn, bought, dealt): it comes in rather than moving
   * from somewhere. */
  entering?: boolean;
};

export type Tone = "chips" | "mult" | "xmult" | "money" | "plain";

/** A short text over a card, or over the board when ``card`` is null. */
export type Popup = { card: number | null; text: string; tone: Tone };

/** The sidebar. */
export type Hud = {
  /** The round's score so far. */
  score: Num;
  /** The hand being scored: its name, level, chips and mult. */
  hand: { name: string; level: Num; chips: Num; mult: Num } | null;
  hands: number;
  discards: number;
  dollars: number;
  ante: number;
  round: number;
};

/** What the board shows at one moment. A frame's resting state is ``sceneOf(frame)``; an
 * action plays out as a list of scenes between two frames' (``buildTimeline``). */
export type Scene = {
  /** The frame the board's fixed parts come from: the blind, the tags, the shop's prices. */
  frame: ReplayFrame;
  phase: string;
  zones: Record<Zone, Slot[]>;
  hud: Hud;
  popups: Popup[];
  /** A line over the board: the hand's total, "Not allowed!", "Cash out $7". */
  banner: string | null;
};

const slots = (cards: ReplayCard[]): Slot[] => cards.map((card) => ({ card }));

export function sceneOf(frame: ReplayFrame): Scene {
  return {
    frame,
    phase: frame.phase,
    zones: {
      jokers: slots(frame.jokers),
      consumables: slots(frame.consumables),
      play: [],
      hand: slots(frame.hand),
      shop: slots(frame.shop.cards),
      vouchers: slots(frame.shop.vouchers),
      boosters: slots(frame.shop.boosters),
      pack: slots(frame.pack),
    },
    hud: {
      score: frame.chips,
      hand: null,
      hands: frame.hands_left,
      discards: frame.discards_left,
      dollars: frame.dollars,
      ante: frame.ante,
      round: frame.round,
    },
    popups: [],
    banner: null,
  };
}

/** Which zone holds a card, and where. */
export function locate(scene: Scene, id: number): { zone: Zone; index: number } | null {
  for (const zone of ZONES) {
    const index = scene.zones[zone].findIndex((s) => s.card.id === id);
    if (index >= 0) return { zone, index };
  }
  return null;
}

/** The same scene with some slots changed. */
export function mapSlots(scene: Scene, f: (slot: Slot, zone: Zone) => Slot): Scene {
  const zones = { ...scene.zones };
  for (const zone of ZONES) zones[zone] = scene.zones[zone].map((s) => f(s, zone));
  return { ...scene, zones };
}

/** Add two game numbers, keeping "inf" and "nan" as the engine writes them. */
export function addNum(a: Num, b: Num): Num {
  const x = toFloat(a) + toFloat(b);
  return Number.isFinite(x) ? x : Number.isNaN(x) ? "nan" : x > 0 ? "inf" : "-inf";
}

export function toFloat(x: Num): number {
  if (typeof x === "number") return x;
  return x === "inf" ? Infinity : x === "-inf" ? -Infinity : NaN;
}
