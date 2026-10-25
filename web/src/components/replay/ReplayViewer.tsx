import { useCallback, useEffect, useRef, useState } from "react";
import type { Frame } from "../../api/client";
import { FRAME_PAGE, useFrames } from "../../api/hooks";
import { StatePanel } from "./StatePanel";

const SPEEDS = [1, 2, 4, 8];

/** Step through an ended episode: a scrubber, play/pause at 1-8 frames a second, the arrow
 * keys, and an action log you can click to jump. Frames load 200 at a time. */
export function ReplayViewer({ episodeId, total, mine = false }: { episodeId: string; total: number; mine?: boolean }) {
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2);
  const page = Math.floor(i / FRAME_PAGE);
  const { data, error } = useFrames(episodeId, page, true, mine);
  const last = total - 1;
  const logRef = useRef<HTMLOListElement>(null);

  // Load the next page before the scrubber gets there.
  const nearEnd = i % FRAME_PAGE > FRAME_PAGE - 40 && (page + 1) * FRAME_PAGE < total;
  useFrames(episodeId, page + 1, nearEnd, mine);

  const go = useCallback((to: number) => setI(Math.max(0, Math.min(last, to))), [last]);

  // Playback stops by itself at the last step: "running" is derived, never set in an effect.
  const running = playing && i < last;
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => setI((x) => Math.min(last, x + 1)), 1000 / speed);
    return () => clearTimeout(timer);
  }, [running, i, last, speed]);

  const toggle = useCallback(() => {
    if (running) setPlaying(false);
    else {
      if (i >= last) setI(0); // play again from the start
      setPlaying(true);
    }
  }, [running, i, last]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) && target.getAttribute("type") !== "range") return;
      if (e.key === "ArrowRight") go(i + 1);
      else if (e.key === "ArrowLeft") go(i - 1);
      else if (e.key === "Home") go(0);
      else if (e.key === "End") go(last);
      else if (e.key === " " && target?.tagName !== "BUTTON") toggle();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, i, last, toggle]);

  useEffect(() => {
    const current = logRef.current?.querySelector<HTMLElement>('[aria-current="step"]');
    current?.scrollIntoView?.({ block: "nearest" });
  }, [i]);

  const frame: Frame | undefined = data?.frames.find((f) => f.i === i);
  return (
    <div className="replay">
      <section className="panel" aria-label="Replay">
        <div className="controls">
          <button type="button" onClick={() => go(0)} aria-label="First step" disabled={i === 0}>
            ⏮
          </button>
          <button type="button" onClick={() => go(i - 1)} aria-label="Previous step" disabled={i === 0}>
            ◀
          </button>
          <button type="button" className="primary" onClick={toggle} aria-pressed={running}>
            {running ? "Pause" : "Play"}
          </button>
          <button type="button" onClick={() => go(i + 1)} aria-label="Next step" disabled={i === last}>
            ▶
          </button>
          <button type="button" onClick={() => go(last)} aria-label="Last step" disabled={i === last}>
            ⏭
          </button>
          <input
            type="range"
            min={0}
            max={last}
            value={i}
            onChange={(e) => go(Number(e.target.value))}
            aria-label="Step"
          />
          <span className="small muted" aria-live="polite">
            step {i} / {last}
          </span>
          <label className="inline small">
            speed
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
              {SPEEDS.map((s) => (
                <option key={s} value={s}>
                  {s}×
                </option>
              ))}
            </select>
          </label>
        </div>
        {error ? (
          <p className="error">Couldn't load this part of the replay.</p>
        ) : frame ? (
          <div style={{ opacity: data ? 1 : 0.5 }}>
            {frame.description && (
              <p className="notice" style={{ marginBottom: "0.75rem" }}>
                <strong>Next:</strong> {frame.description}
              </p>
            )}
            <StatePanel frame={frame} />
          </div>
        ) : (
          <p className="muted">Loading…</p>
        )}
      </section>
      <aside className="panel" aria-label="Actions">
        <h2>Actions</h2>
        <ol className="log" ref={logRef}>
          {data?.frames
            .filter((f) => f.description)
            .map((f) => (
              <li key={f.i}>
                <button type="button" onClick={() => go(f.i)} aria-current={f.i === i ? "step" : undefined}>
                  <span className="i">{f.i}</span>
                  <span>{f.description}</span>
                </button>
              </li>
            ))}
        </ol>
        {total > FRAME_PAGE && (
          <p className="small muted">
            Showing steps {page * FRAME_PAGE}–{Math.min(last, (page + 1) * FRAME_PAGE - 1)}.
          </p>
        )}
      </aside>
    </div>
  );
}
