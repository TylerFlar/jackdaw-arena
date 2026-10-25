import { describe, expect, it } from "vitest";
import type { ReplayFrame } from "../api/client";
import fixtures from "./fixtures.json";
import { locate, sceneOf, ZONES } from "./scene";
import { atRest, buildTimeline, type Beat } from "./timeline";

// Real frames from jackdaw's smart agent on seed SAMPLE42 (api/src/arena/engine/replay.py):
// each entry is a frame and the one its action leads to.
const pairs = fixtures as unknown as Record<string, [ReplayFrame, ReplayFrame]>;
const timeline = (name: string): [Beat[], ReplayFrame, ReplayFrame] => {
  const [prev, next] = pairs[name]!;
  return [buildTimeline(prev, next), prev, next];
};

describe("timelines", () => {
  it("end on the next frame's scene, whatever the action", () => {
    for (const [prev, next] of Object.values(pairs)) {
      const beats = buildTimeline(prev, next);
      expect(atRest(beats.at(-1)!.scene)).toEqual(sceneOf(next));
      expect(beats.every((b) => b.ms > 0)).toBe(true);
    }
  });

  it("play a hand: into play, every event in turn, the total, then the score", () => {
    const [beats, prev, next] = timeline("play");
    const play = prev.outcome!.play!;
    // The played cards leave the hand for the play area, in play order.
    const inPlay = beats.find((b) => b.scene.zones.play.length > 0)!.scene;
    expect(inPlay.zones.play.map((s) => s.card.id)).toEqual(play.played);
    expect(inPlay.zones.hand.some((s) => play.played.includes(s.card.id))).toBe(false);
    // The sidebar follows each event's running chips and mult.
    const shown = beats.filter((b) => b.scene.hud.hand).map((b) => [b.scene.hud.hand!.chips, b.scene.hud.hand!.mult]);
    expect(shown).toEqual(expect.arrayContaining(play.events.map((e) => [e.hand_chips, e.hand_mult])));
    // A joker's effect pops up on the joker, and the scoring cards lift.
    const joker = play.events.find((e) => e.kind === "joker")!;
    const jokerBeat = beats.find((b) => b.scene.popups.some((p) => p.card === joker.card && p.tone === "mult"))!;
    expect(jokerBeat.scene.popups).toEqual([{ card: joker.card, text: `+${joker.mult} Mult`, tone: "mult" }]);
    expect(jokerBeat.scene.zones.play.filter((s) => s.raised).map((s) => s.card.id)).toEqual(play.scoring);
    // The total, then the round's score.
    expect(beats.some((b) => b.scene.banner === `${play.hand}: ${next.last_score!.total}`)).toBe(true);
    // Then the played cards fade out, and the next frame has none in play.
    expect(beats.at(-2)!.scene.zones.play.every((s) => s.leaving)).toBe(true);
    expect(beats.at(-2)!.scene.hud.score).toBe(next.chips);
    expect(beats.at(-1)!.scene.zones.play).toEqual([]);
    // Cards come in only when the moment before didn't show them. This play wins the round,
    // so the rest of the hand leaves with the played cards.
    const before = new Set(ZONES.flatMap((z) => beats.at(-2)!.scene.zones[z].map((s) => s.card.id)));
    for (const zone of ZONES) {
      for (const s of beats.at(-1)!.scene.zones[zone]) expect(Boolean(s.entering)).toBe(!before.has(s.card.id));
    }
    expect(next.phase).toBe("round_eval");
    expect(beats.at(-2)!.scene.zones.hand.every((s) => s.leaving)).toBe(true);
  });

  it("discard: the chosen cards lift, then leave", () => {
    const [beats, prev] = timeline("discard");
    const chosen = (prev.action![1] as number[]).map((i) => prev.hand[i]!.id);
    expect(beats[0]!.scene.zones.hand.filter((s) => s.raised).map((s) => s.card.id)).toEqual(chosen);
    const gone = beats[1]!.scene.zones.hand.filter((s) => s.leaving).map((s) => s.card.id);
    expect(gone).toEqual(chosen);
    expect(beats[2]!.scene.zones.hand.some((s) => chosen.includes(s.card.id))).toBe(false);
  });

  it("cash out, buy, and a planet: a banner or the card moving", () => {
    const [cash, prev] = timeline("cash_out");
    expect(cash.some((b) => b.scene.banner === `Cash out $${prev.outcome!.cash_out}`)).toBe(true);
    const [buy, shop, after] = timeline("buy");
    const bought = shop.shop.cards[shop.action![1] as number]!.id;
    expect(buy[0]!.scene.zones.shop.find((s) => s.card.id === bought)).toMatchObject({ raised: true, active: true });
    expect(locate(sceneOf(after), bought)?.zone).toMatch(/jokers|consumables/);
    const [planet, used] = timeline("level_up");
    const up = used.outcome!.level_ups![0]!;
    expect(planet.some((b) => b.scene.banner?.includes(`${up.hand} level ${up.level}`))).toBe(true);
  });

  it("give every card one place at a time", () => {
    for (const [prev, next] of Object.values(pairs)) {
      for (const { scene } of buildTimeline(prev, next)) {
        const seen = ZONES.flatMap((z) => scene.zones[z].map((s) => s.card.id));
        expect(new Set(seen).size).toBe(seen.length);
      }
    }
  });
});
