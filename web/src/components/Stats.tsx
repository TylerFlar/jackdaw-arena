import type { ReactNode } from "react";

/** A stat tile: label, value (proportional figures), an optional line under it. */
export function StatTile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

/** A mean and its 95% interval on a shared scale: a dot (with a surface ring) on a 2px line.
 * One series, so no legend; the row's numbers sit beside it, and the title carries them too. */
export function IntervalMark({
  mean,
  ci,
  max,
  width = 132,
}: {
  mean: number;
  ci: readonly number[] | null | undefined;
  max: number;
  width?: number;
}) {
  const pad = 6;
  const x = (v: number) => pad + (Math.max(0, Math.min(v, max)) / (max || 1)) * (width - 2 * pad);
  const lo = ci?.[0] ?? mean;
  const hi = ci?.[1] ?? mean;
  const label = `mean ${mean.toFixed(2)}${ci ? `, 95% CI ${lo.toFixed(2)} to ${hi.toFixed(2)}` : ""}`;
  return (
    <svg className="interval" width={width} height={16} viewBox={`0 0 ${width} 16`} role="img" aria-label={label}>
      <title>{label}</title>
      <line className="track" x1={pad} x2={width - pad} y1={8} y2={8} />
      <line className="ci" x1={x(lo)} x2={x(hi)} y1={8} y2={8} />
      <circle className="dot" cx={x(mean)} cy={8} r={4} />
    </svg>
  );
}
