/** Numbers as the site shows them. Game numbers may arrive as "inf" (scores overflow). */
export type Num = number | string | null | undefined;

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });

export function num(x: Num): string {
  if (x === null || x === undefined) return "-";
  if (typeof x === "string") return x === "inf" ? "∞" : x === "-inf" ? "-∞" : x;
  return Math.abs(x) >= 1e6 ? compact.format(x) : whole.format(x);
}

export function fixed(x: number | null | undefined, digits = 2): string {
  return x === null || x === undefined ? "-" : x.toFixed(digits);
}

export function pct(x: number | null | undefined, digits = 1): string {
  return x === null || x === undefined ? "-" : `${(100 * x).toFixed(digits)}%`;
}

export function interval(ci: [number, number] | readonly number[] | null | undefined, digits = 2, asPct = false): string {
  if (!ci || ci.length < 2) return "-";
  const f = (v: number) => (asPct ? pct(v, digits) : v.toFixed(digits));
  return `${f(ci[0]!)} – ${f(ci[1]!)}`;
}

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "-";
  const seconds = (new Date(iso).getTime() - now) / 1000;
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

export function shortHash(h: string | null | undefined): string {
  return h ? `${h.slice(0, 10)}…` : "-";
}

const END_REASONS: Record<string, string> = {
  won: "won",
  lost: "lost",
  max_steps: "hit the step cap",
  refused: "refused (env bug)",
  not_ported: "not ported (engine gap)",
  engine_error: "engine error",
  forfeit: "forfeited",
  idle: "timed out",
};

export function endReason(reason: string | null | undefined): string {
  return reason ? (END_REASONS[reason] ?? reason) : "-";
}
