import { useEffect, useId, useMemo, useRef, useState } from "react";

/** Episodes by blinds beaten: one series of columns in slot-1 blue. Columns are at most 24px,
 * with a 4px rounded data-end, square at the baseline, and hairline grid. Each column has a
 * hover/focus tooltip, and a table view is one click away. */
export function Histogram({ counts, title }: { counts: number[]; title: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const id = useId();
  // Draw at the container's real width, so 1 unit is 1px: text stays 11px and columns stay
  // <= 24px at any size (a scaled viewBox would blow both up on wide screens).
  const box = useRef<HTMLDivElement>(null);
  const W = useWidth(box, 640);
  const H = 220;
  const m = { top: 12, right: 8, bottom: 30, left: 36 };
  const plotW = W - m.left - m.right;
  const plotH = H - m.top - m.bottom;
  const max = Math.max(1, ...counts);
  const ticks = useMemo(() => niceTicks(max), [max]);
  const top = ticks[ticks.length - 1] ?? max;
  const band = plotW / Math.max(1, counts.length);
  const barW = Math.min(24, band - 2); // never fill the band: the leftover is air (>= 2px gap)
  const y = (v: number) => m.top + plotH - (v / top) * plotH;
  const total = counts.reduce((a, b) => a + b, 0);

  if (!counts.length) return <p className="muted">No ended episodes yet.</p>;

  return (
    <figure className="chart" style={{ margin: 0 }} aria-labelledby={`${id}-t`}>
      <div className="row" style={{ marginBottom: "0.4rem" }}>
        <h3 id={`${id}-t`} style={{ margin: 0 }}>
          {title}
        </h3>
        <span className="spacer" />
        <button type="button" onClick={() => setTable(!table)} aria-pressed={table}>
          {table ? "Show chart" : "Show table"}
        </button>
      </div>
      {table ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num">Blinds beaten</th>
                <th className="num">Episodes</th>
                <th className="num">Share</th>
              </tr>
            </thead>
            <tbody>
              {counts.map((c, b) => (
                <tr key={b}>
                  <td className="num">{b}</td>
                  <td className="num">{c}</td>
                  <td className="num">{total ? `${((100 * c) / total).toFixed(1)}%` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ position: "relative" }} ref={box}>
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: ${total} episodes`}>
            {ticks.map((t) => (
              <g key={t}>
                <line className="gridline" x1={m.left} x2={W - m.right} y1={y(t)} y2={y(t)} />
                <text className="tick" x={m.left - 6} y={y(t)} dy="0.32em" textAnchor="end">
                  {t.toLocaleString("en")}
                </text>
              </g>
            ))}
            {counts.map((c, b) => {
              const cx = m.left + band * b + band / 2;
              const h = (c / top) * plotH;
              return (
                <g key={b}>
                  <rect
                    className="hit"
                    x={m.left + band * b}
                    y={m.top}
                    width={band}
                    height={plotH}
                    fill="transparent"
                    tabIndex={0}
                    aria-label={`${c} episodes beat ${b} blinds`}
                    onPointerEnter={() => setHover(b)}
                    onPointerLeave={() => setHover(null)}
                    onFocus={() => setHover(b)}
                    onBlur={() => setHover(null)}
                  />
                  {c > 0 && (
                    <path
                      className={`bar${hover === b ? " active" : ""}`}
                      d={roundedTop(cx - barW / 2, y(c), barW, h, 4)}
                      pointerEvents="none"
                    />
                  )}
                  {(counts.length <= 16 || b % 2 === 0) && (
                    <text className="tick" x={cx} y={H - m.bottom + 16} textAnchor="middle">
                      {b}
                    </text>
                  )}
                </g>
              );
            })}
            <line className="baseline" x1={m.left} x2={W - m.right} y1={m.top + plotH} y2={m.top + plotH} />
            <text className="tick" x={m.left + plotW / 2} y={H - 2} textAnchor="middle">
              blinds beaten
            </text>
          </svg>
          {hover !== null && (
            <div
              className="tooltip"
              role="status"
              style={{
                left: `${((m.left + band * hover + band / 2) / W) * 100}%`,
                top: `${(y(counts[hover] ?? 0) / H) * 100}%`,
              }}
            >
              <strong>{counts[hover]}</strong> episodes · {hover} blinds beaten
            </div>
          )}
        </div>
      )}
    </figure>
  );
}

function useWidth(ref: React.RefObject<HTMLElement | null>, fallback: number): number {
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const w = Math.round(entry?.contentRect.width ?? 0);
      if (w > 0) setWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/** A column path with rounded top corners and a square base. */
export function roundedTop(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.max(0, Math.min(r, w / 2, h));
  const b = y + h;
  return `M${x},${b}L${x},${y + rr}Q${x},${y} ${x + rr},${y}L${x + w - rr},${y}Q${x + w},${y} ${x + w},${y + rr}L${x + w},${b}Z`;
}

/** Clean tick values (1, 2, 5 x 10^k) from 0 to at least ``max``. */
export function niceTicks(max: number, count = 4): number[] {
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const step = [1, 2, 5, 10].map((s) => s * mag).find((s) => s >= raw) ?? mag;
  const out: number[] = [];
  for (let v = 0; v <= max + step * 0.999; v += step) out.push(Math.round(v * 1e6) / 1e6);
  return out;
}
