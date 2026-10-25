import { describe, expect, it } from "vitest";
import { player, START, type PlayerState } from "./player";
import type { Beat } from "./timeline";

const beats = (n: number) => Array.from({ length: n }, (_, k) => ({ ms: 100 + k }) as unknown as Beat);

describe("player", () => {
  it("plays an action out moment by moment, then rests on the next frame", () => {
    let s: PlayerState = player(START, { type: "animate", beats: beats(3) });
    expect([s.i, s.beat]).toEqual([0, 0]);
    s = player(s, { type: "tick" });
    s = player(s, { type: "tick" });
    expect([s.i, s.beat]).toEqual([0, 2]);
    s = player(s, { type: "tick" });
    expect(s).toEqual({ ...START, i: 1 });
  });

  it("finishes the running action at once, and ignores a second one meanwhile", () => {
    let s = player(START, { type: "animate", beats: beats(5) });
    s = player(s, { type: "animate", beats: beats(2) });
    expect(s.beats).toHaveLength(5);
    s = player(s, { type: "finish" });
    expect(s).toEqual({ ...START, i: 1 });
    expect(player(s, { type: "finish" })).toBe(s);
  });

  it("jumps without playing anything out, and keeps playing on if it was", () => {
    let s = player(START, { type: "play" });
    s = player(s, { type: "animate", beats: beats(4) });
    s = player(s, { type: "seek", i: 40 });
    expect(s).toEqual({ i: 40, beats: null, beat: 0, playing: true });
    expect(player(s, { type: "seek", i: -3 }).i).toBe(0);
    expect(player(s, { type: "pause" }).playing).toBe(false);
  });
});
