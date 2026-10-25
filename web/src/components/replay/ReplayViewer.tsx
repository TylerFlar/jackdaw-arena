import { useEffect, useRef, useState } from "react";
import { REPLAY_PAGE, SPEEDS, usePlayer, useSpeed, type Speed } from "../../replay/useReplay";
import { Board } from "./Board";
import { StatePanel } from "./StatePanel";

/** An ended episode, played back on a Balatro board. Play runs it on, each action playing out
 * (a hand's cards scoring one by one); → plays out one action, Shift+→, ← and the scrubber jump.
 * The action log beside it jumps to any step. */
export function ReplayViewer({ episodeId, mine = false }: { episodeId: string; mine?: boolean }) {
  const [speed, setSpeed] = useSpeed();
  const [text, setText] = useState(false);
  const p = usePlayer(episodeId, mine, speed);
  const logRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) && target.getAttribute("type") !== "range") return;
      if (e.key === "ArrowRight") {
        if (e.shiftKey) p.seek(p.i + 1);
        else p.next();
      } else if (e.key === "ArrowLeft") p.seek(p.i - 1);
      else if (e.key === "Home") p.seek(0);
      else if (e.key === "End") p.seek(p.last);
      else if (e.key === " " && target?.tagName !== "BUTTON") p.toggle();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p]);

  useEffect(() => {
    const current = logRef.current?.querySelector<HTMLElement>('[aria-current="step"]');
    current?.scrollIntoView?.({ block: "nearest" });
  }, [p.i]);

  if (!p.scene || !p.frame || p.total === undefined) {
    return (
      <section className="panel" aria-label="Replay">
        {p.error ? <p className="error">The replay couldn't load.</p> : <p className="muted">Loading the replay…</p>}
      </section>
    );
  }

  const page = Math.floor(p.i / REPLAY_PAGE);
  const log = Array.from({ length: Math.min(REPLAY_PAGE, p.total - page * REPLAY_PAGE) }, (_, k) =>
    p.frameAt(page * REPLAY_PAGE + k),
  ).filter((f) => f?.description);
  return (
    <div className="replay">
      <section className="panel board-panel" aria-label="Replay">
        <div className="controls">
          <button type="button" onClick={() => p.seek(0)} aria-label="First step" disabled={p.i === 0}>
            ⏮
          </button>
          <button type="button" onClick={() => p.seek(p.i - 1)} aria-label="Previous step" disabled={p.i === 0}>
            ◀
          </button>
          <button type="button" className="primary" onClick={p.toggle} aria-pressed={p.running}>
            {p.running ? "Pause" : "Play"}
          </button>
          <button type="button" onClick={p.next} aria-label="Next step" disabled={p.i >= p.last && !p.animating}>
            ▶
          </button>
          <button type="button" onClick={() => p.seek(p.last)} aria-label="Last step" disabled={p.i >= p.last}>
            ⏭
          </button>
          <input
            type="range"
            min={0}
            max={p.last}
            value={p.i}
            onChange={(e) => p.seek(Number(e.target.value))}
            aria-label="Step"
          />
          <span className="small muted" aria-live="polite">
            step {p.i} / {p.last}
          </span>
          <label className="inline small">
            speed
            <select
              value={String(speed)}
              onChange={(e) => setSpeed(SPEEDS.find((s) => String(s) === e.target.value) ?? 1)}
            >
              {SPEEDS.map((s: Speed) => (
                <option key={s} value={String(s)}>
                  {s === "instant" ? "Instant" : `${s}×`}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="small" onClick={() => setText((t) => !t)} aria-pressed={text}>
            Text view
          </button>
        </div>
        {p.frame.description && (
          <p className="next-line">
            <strong>Next:</strong> {p.frame.description}
          </p>
        )}
        {text ? (
          <StatePanel frame={p.frame} />
        ) : (
          <Board scene={p.scene} animating={p.animating} speed={speed === "instant" ? 1 : speed} />
        )}
      </section>
      <aside className="panel" aria-label="Actions">
        <h2>Actions</h2>
        <ol className="log" ref={logRef}>
          {log.map((f) => (
            <li key={f!.i}>
              <button type="button" onClick={() => p.seek(f!.i)} aria-current={f!.i === p.i ? "step" : undefined}>
                <span className="i">{f!.i}</span>
                <span>{f!.description}</span>
              </button>
            </li>
          ))}
        </ol>
        {p.total > REPLAY_PAGE && (
          <p className="small muted">
            Showing steps {page * REPLAY_PAGE}–{Math.min(p.last, (page + 1) * REPLAY_PAGE - 1)}.
          </p>
        )}
      </aside>
    </div>
  );
}
