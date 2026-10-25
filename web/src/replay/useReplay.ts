import { useQueries, type UseQueryResult } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { api, unwrap, type ReplayDoc, type ReplayFrame } from "../api/client";
import { player, START } from "./player";
import { sceneOf } from "./scene";
import { buildTimeline } from "./timeline";

export const REPLAY_PAGE = 200;

/** The replay's frames around frame ``i``: its page, the next frame's, and the page after
 * once ``i`` nears the end of its own. The frame count comes from the server: a tape can be
 * shorter than the episode's step count. */
export function useReplayFrames(id: string, mine: boolean, i: number) {
  const page = Math.floor(i / REPLAY_PAGE);
  const pages = [...new Set([0, page, Math.floor((i + 1) / REPLAY_PAGE), ...(i % REPLAY_PAGE > REPLAY_PAGE - 40 ? [page + 1] : [])])];
  return useQueries({
    combine,
    queries: pages.map((p) => ({
      queryKey: ["replay", id, p, mine],
      staleTime: Infinity,
      queryFn: () => {
        const params = { path: { episode_id: id }, query: { from: p * REPLAY_PAGE, limit: REPLAY_PAGE } };
        return unwrap(
          mine
            ? api.GET("/api/me/episodes/{episode_id}/replay", { params })
            : api.GET("/api/episodes/{episode_id}/replay", { params }),
        );
      },
    })),
  });
}

/** The loaded pages as one replay. TanStack Query reruns it only when a page's result changes,
 * so ``frameAt`` keeps its identity otherwise, and so do the player's timers. */
function combine(results: UseQueryResult<ReplayDoc>[]) {
  const docs = new Map<number, ReplayDoc>();
  for (const r of results) if (r.data) docs.set(r.data.start / REPLAY_PAGE, r.data);
  const frameAt = (n: number): ReplayFrame | undefined => docs.get(Math.floor(n / REPLAY_PAGE))?.frames[n % REPLAY_PAGE];
  const first = docs.get(0) ?? [...docs.values()][0];
  return { total: first?.total, frameAt, error: results.find((r) => r.error)?.error ?? null };
}

export type Speed = 1 | 2 | 4 | "instant";
export const SPEEDS: Speed[] = [1, 2, 4, "instant"];
const KEY = "replay-speed";

function parseSpeed(x: string | null | undefined): Speed | undefined {
  return SPEEDS.find((s) => String(s) === x);
}

/** The playback speed: ``?speed=`` first, then the viewer's last choice, else 1×. With reduced
 * motion asked for, steps jump. */
export function useSpeed(): [Speed, (s: Speed) => void] {
  const [speed, setSpeed] = useState<Speed>(() => {
    const fromUrl = parseSpeed(new URLSearchParams(globalThis.location?.search ?? "").get("speed"));
    if (fromUrl) return fromUrl;
    try {
      const saved = parseSpeed(globalThis.localStorage?.getItem(KEY));
      if (saved) return saved;
    } catch {
      // Storage can be off (a private window): the default does.
    }
    return globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "instant" : 1;
  });
  const set = useCallback((s: Speed) => {
    setSpeed(s);
    try {
      globalThis.localStorage?.setItem(KEY, String(s));
    } catch {
      // Not remembered then.
    }
  }, []);
  return [speed, set];
}

/** Rest between actions while playing on, at 1×. */
const PAUSE_MS = 450;

/** The replay's position and what the board shows: a frame at rest, or its action playing out. */
export function usePlayer(id: string, mine: boolean, speed: Speed) {
  const [state, dispatch] = useReducer(player, START);
  const { total, frameAt, error } = useReplayFrames(id, mine, state.i);
  const last = (total ?? 1) - 1;
  const factor = speed === "instant" ? Infinity : speed;

  const next = useCallback(() => {
    if (state.beats) return dispatch({ type: "finish" });
    if (state.i >= last) return;
    const from = frameAt(state.i);
    const to = frameAt(state.i + 1);
    if (!from || !to) return; // not loaded yet: loading it renders again
    if (speed === "instant") dispatch({ type: "seek", i: state.i + 1 });
    else dispatch({ type: "animate", beats: buildTimeline(from, to) });
  }, [state.beats, state.i, last, frameAt, speed]);

  const seek = useCallback((i: number) => dispatch({ type: "seek", i: Math.max(0, Math.min(last, i)) }), [last]);

  // The running action's moments, one after another.
  const beat = state.beats?.[state.beat];
  useEffect(() => {
    if (!beat) return;
    const timer = setTimeout(() => dispatch({ type: "tick" }), beat.ms / factor);
    return () => clearTimeout(timer);
  }, [beat, factor]);

  // Playing on: the next action after a rest, until the end.
  const running = state.playing && state.i < last;
  useEffect(() => {
    if (!running || state.beats) return;
    const timer = setTimeout(next, speed === "instant" ? 140 : PAUSE_MS / factor);
    return () => clearTimeout(timer);
  }, [running, state.beats, next, speed, factor]);

  const frame = frameAt(state.i);
  const scene = useMemo(() => beat?.scene ?? (frame ? sceneOf(frame) : null), [beat, frame]);
  return {
    i: state.i,
    last,
    total,
    error,
    frame,
    scene,
    animating: Boolean(state.beats),
    running,
    frameAt,
    next,
    seek,
    toggle: () => {
      if (running) dispatch({ type: "pause" });
      else {
        if (state.i >= last) seek(0); // play again from the start
        dispatch({ type: "play" });
      }
    },
    pause: () => dispatch({ type: "pause" }),
  };
}
