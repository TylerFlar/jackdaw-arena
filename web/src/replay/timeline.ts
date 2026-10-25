import type { PlayOutcome, ReplayFrame, ScoreEvent } from "../api/client";
import { num } from "../lib/format";
import { addNum, mapSlots, sceneOf, ZONES, type Popup, type Scene } from "./scene";

/** One moment of an action playing out: the scene, and how long it holds at 1×. */
export type Beat = { scene: Scene; ms: number };

/** How long each kind of moment holds at 1×, in milliseconds. */
export const MS = {
  raise: 240,
  move: 380,
  hand: 460,
  event: 380,
  again: 340,
  total: 600,
  score: 500,
  clear: 380,
  banner: 760,
  rest: 420,
} as const;

/** How the action of ``prev`` plays out, ending on ``next``. The last scene is always
 * ``sceneOf(next)``: an animated step ends exactly where a jump lands. */
export function buildTimeline(prev: ReplayFrame, next: ReplayFrame): Beat[] {
  const kind = prev.action?.[0];
  const beats =
    kind === "PlayHand" ? playHand(prev, next) : kind === "Discard" ? discard(prev, next) : generic(prev, next);
  beats.push({ scene: sceneOf(next), ms: MS.rest });
  // Mark the cards each moment brings onto the board.
  let before = ids(sceneOf(prev));
  return beats.map(({ scene, ms }) => {
    const marked = mapSlots(scene, (slot) => (before.has(slot.card.id) ? slot : { ...slot, entering: true }));
    before = ids(scene);
    return { scene: marked, ms };
  });
}

/** A scene without its ``entering`` marks: what a frame shows at rest. */
export function atRest(scene: Scene): Scene {
  return mapSlots(scene, ({ entering: _, ...slot }) => slot);
}

const isId = (x: number | undefined): x is number => typeof x === "number";

/** The hand cards an action selected, by position. */
function selected(prev: ReplayFrame): Set<number> {
  const positions = (prev.action?.[1] as number[] | undefined) ?? [];
  return new Set(positions.map((i) => prev.hand[i]?.id).filter(isId));
}

function raise(scene: Scene, ids: Set<number>, zone: "hand" | "play"): Scene {
  return mapSlots(scene, (slot, z) => (z === zone && ids.has(slot.card.id) ? { ...slot, raised: true } : slot));
}

/** The scene without its passing parts: popups, pulses, the banner. */
function settle(scene: Scene): Scene {
  return { ...mapSlots(scene, ({ active: _, ...slot }) => slot), popups: [], banner: null };
}

function playHand(prev: ReplayFrame, next: ReplayFrame): Beat[] {
  const play = prev.outcome?.play;
  const chosen = play ? new Set(play.played) : selected(prev);
  let s = raise(sceneOf(prev), chosen, "hand");
  const beats: Beat[] = [{ scene: s, ms: MS.raise }];
  if (!play) return beats;

  // Into the play area, in play order.
  const cards = new Map(prev.hand.map((c) => [c.id, c]));
  s = {
    ...s,
    zones: {
      ...s.zones,
      hand: s.zones.hand.filter((slot) => !chosen.has(slot.card.id)),
      play: play.played.flatMap((id) => {
        const card = cards.get(id);
        return card ? [{ card }] : [];
      }),
    },
  };
  beats.push({ scene: s, ms: MS.move });

  for (const e of play.events) {
    const [base, beat] = eventBeat(s, e, play);
    s = base;
    beats.push(beat);
  }

  // The total, then the round's score.
  const total = next.last_score?.total ?? 0;
  s = { ...settle(s), banner: `${play.hand}: ${num(total)}` };
  beats.push({ scene: s, ms: MS.total });
  s = { ...s, banner: null, hud: { ...s.hud, score: addNum(prev.chips, total) } };
  beats.push({ scene: s, ms: MS.score });
  // The played cards go to the discard pile (or were destroyed), and so does the hand when
  // the round is over.
  beats.push({ scene: leave({ ...s, hud: { ...s.hud, hand: null } }, next, "discard"), ms: MS.clear });
  return beats;
}

/** Cards not on the next frame's board fade out where they are. */
function leave(s: Scene, next: ReplayFrame, how: "discard" | "dissolve"): Scene {
  const kept = ids(sceneOf(next));
  return mapSlots(s, (slot) => (kept.has(slot.card.id) ? slot : { ...slot, leaving: slot.leaving ?? how }));
}

/** What an event shows (popups, pulses, a banner), and the scene it leaves for the next. */
function eventBeat(s: Scene, e: ScoreEvent, play: PlayOutcome): [Scene, Beat] {
  let base: Scene = { ...s };
  const popups: Popup[] = [];
  let banner: string | null = null;
  let ms: number = MS.event;
  const hand = { name: play.hand, level: e.level ?? s.hud.hand?.level ?? play.level, chips: e.hand_chips, mult: e.hand_mult };
  switch (e.kind) {
    case "level_up":
      popups.push({ card: e.card ?? null, text: "Level up!", tone: "plain" });
      ms = MS.hand;
      break;
    case "hand":
      // The hand's base, and the cards that score lift.
      base = raise(base, new Set(play.scoring), "play");
      ms = MS.hand;
      break;
    case "blind":
      banner = "The boss halves the hand";
      ms = MS.banner;
      break;
    case "not_allowed":
      banner = "Not allowed!";
      ms = MS.banner;
      break;
    case "plasma":
      banner = "Balanced";
      ms = MS.banner;
      break;
    case "retrigger":
      popups.push({ card: e.card ?? null, text: "Again!", tone: "plain" });
      ms = MS.again;
      break;
    case "debuffed":
      popups.push({ card: e.card ?? null, text: "Debuffed", tone: "plain" });
      break;
    case "destroyed":
      base = mapSlots(base, (slot, zone) =>
        zone === "play" && slot.card.id === e.card ? { ...slot, leaving: e.shattered ? "shatter" : "dissolve" } : slot,
      );
      ms = MS.again;
      break;
    default:
      popups.push(...effectPopups(e));
  }
  base = { ...base, hud: { ...base.hud, hand } };
  const pulse = new Set([e.card, e.target].filter((x): x is number => typeof x === "number"));
  const shown = { ...mapSlots(base, (slot) => (pulse.has(slot.card.id) ? { ...slot, active: true } : slot)), popups, banner };
  return [base, { scene: shown, ms }];
}

/** The game's popups for what an effect added: "+10" chips, "+4 Mult", "X2", "$3". */
export function effectPopups(e: ScoreEvent): Popup[] {
  const card = e.card ?? null;
  const out: Popup[] = [];
  if (e.chips != null) out.push({ card, text: `+${num(e.chips)}`, tone: "chips" });
  if (e.mult != null) out.push({ card, text: `+${num(e.mult)} Mult`, tone: "mult" });
  if (e.x_mult != null) out.push({ card, text: `X${num(e.x_mult)}`, tone: "xmult" });
  if (e.dollars != null) out.push({ card, text: money(e.dollars), tone: "money" });
  if (e.swap) out.push({ card, text: "Swap!", tone: "plain" });
  return out;
}

function money(x: number | string): string {
  const n = typeof x === "number" ? x : Number(x);
  return n < 0 ? `-$${num(-n)}` : `$${num(x)}`;
}

function discard(prev: ReplayFrame, next: ReplayFrame): Beat[] {
  const s = raise(sceneOf(prev), selected(prev), "hand");
  return [
    { scene: s, ms: MS.raise },
    { scene: leave(s, next, "discard"), ms: MS.clear },
  ];
}

/** The card an action takes, uses, buys or sells. */
function subject(prev: ReplayFrame): number | undefined {
  const a = prev.action ?? [];
  const i = a[1] as number;
  switch (a[0]) {
    case "BuyCard":
    case "BuyAndUse":
      return prev.shop.cards[i]?.id;
    case "RedeemVoucher":
      return prev.shop.vouchers[i]?.id;
    case "OpenBooster":
      return prev.shop.boosters[i]?.id;
    case "UseConsumable":
      return prev.consumables[i]?.id;
    case "PickPackCard":
      return prev.pack[i]?.id;
    case "SellCard":
      return (a[1] === "jokers" ? prev.jokers : prev.consumables)[a[2] as number]?.id;
  }
  return undefined;
}

function ids(s: Scene): Set<number> {
  return new Set(ZONES.flatMap((z) => s.zones[z].map((slot) => slot.card.id)));
}

function generic(prev: ReplayFrame, next: ReplayFrame): Beat[] {
  const beats: Beat[] = [];
  let s = sceneOf(prev);
  const id = subject(prev);
  if (id !== undefined) {
    s = mapSlots(s, (slot) => (slot.card.id === id ? { ...slot, raised: true, active: true } : slot));
    beats.push({ scene: s, ms: MS.raise });
    s = settle(s);
  }
  // Cards that leave the board (sold, used, a shop left behind) dissolve where they are.
  const kept = ids(sceneOf(next));
  if ([...ids(s)].some((x) => !kept.has(x))) {
    s = leave(s, next, "dissolve");
    beats.push({ scene: s, ms: MS.clear });
  }
  const banner = outcomeBanner(prev, next);
  const change = next.dollars - prev.dollars;
  const popups: Popup[] = change && !prev.outcome?.cash_out ? [{ card: null, text: money(change), tone: "money" }] : [];
  if (banner || popups.length) beats.push({ scene: { ...s, banner, popups }, ms: banner ? MS.banner : MS.event });
  return beats;
}

/** A line for what an action did: the cash out, a hand levelled up, the blind chosen. */
function outcomeBanner(prev: ReplayFrame, next: ReplayFrame): string | null {
  const o = prev.outcome;
  if (o?.cash_out != null) return `Cash out ${money(o.cash_out)}`;
  if (o?.level_ups?.length) return o.level_ups.map((u) => `${u.hand} level ${num(u.level)}`).join(" · ");
  const kind = prev.action?.[0];
  if (kind === "SelectBlind" && next.blind) return `${next.blind.name}: score ${num(next.blind.chips)}`;
  if (kind === "SkipBlind") {
    const on = Object.values(prev.blinds ?? {}).find((b) => b.status === "SELECT");
    return on?.tag ? `Skipped for the ${on.tag}` : "Skipped";
  }
  return null;
}
