import type { Beat } from "./timeline";

/** Where the replay is: at frame ``i`` (the state before its action), or that action playing
 * out, moment by moment. */
export type PlayerState = {
  i: number;
  /** The action of frame ``i`` playing out, and the moment it's at. */
  beats: Beat[] | null;
  beat: number;
  /** Playing on by itself. */
  playing: boolean;
};

export type PlayerAction =
  /** Jump to a frame, with nothing played out. */
  | { type: "seek"; i: number }
  /** Play out frame ``i``'s action. */
  | { type: "animate"; beats: Beat[] }
  /** The moment's time is up. */
  | { type: "tick" }
  /** Skip to the end of the action playing out. */
  | { type: "finish" }
  | { type: "play" }
  | { type: "pause" };

export const START: PlayerState = { i: 0, beats: null, beat: 0, playing: false };

const done = (s: PlayerState): PlayerState => ({ ...s, i: s.i + 1, beats: null, beat: 0 });

export function player(s: PlayerState, a: PlayerAction): PlayerState {
  switch (a.type) {
    case "seek":
      return { ...s, i: Math.max(0, a.i), beats: null, beat: 0 };
    case "animate":
      return s.beats || !a.beats.length ? s : { ...s, beats: a.beats, beat: 0 };
    case "tick":
      if (!s.beats) return s;
      return s.beat + 1 < s.beats.length ? { ...s, beat: s.beat + 1 } : done(s);
    case "finish":
      return s.beats ? done(s) : s;
    case "play":
      return { ...s, playing: true };
    case "pause":
      return { ...s, playing: false };
  }
}
