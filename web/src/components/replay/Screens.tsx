import { useNames } from "../../api/catalog";
import type { ReplayFrame } from "../../api/client";
import { Icon } from "../../art/Icon";
import { num } from "../../lib/format";

const STATUS: Record<string, string> = {
  SELECT: "Up next",
  CURRENT: "Playing",
  UPCOMING: "Upcoming",
  DEFEATED: "Defeated",
  SKIPPED: "Skipped",
};

/** The blind-select screen: small, big and boss blinds with their targets and skip tags. */
export function BlindChoices({ frame }: { frame: ReplayFrame }) {
  const names = useNames();
  return (
    <div className="blind-choices">
      {(["small", "big", "boss"] as const).map((slot) => {
        const b = frame.blinds?.[slot];
        if (!b) return null;
        return (
          <div key={slot} className={`blind-choice ${(b.status ?? "").toLowerCase()}`}>
            <span className="status">{STATUS[b.status ?? ""] ?? b.status}</span>
            <Icon atlas="blinds" entry={b.key ? names.info(b.key) : undefined} />
            <strong>{b.name}</strong>
            <span>
              Score at least <b className="target">{num(b.score)}</b>
            </span>
            {b.tag && (
              <span className="skip">
                or skip for <Icon atlas="tags" entry={b.tag_key ? names.info(b.tag_key) : undefined} /> {b.tag}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** The blind just beaten. By the round's end the run's blind is cleared, but the blind row
 * still has the round: it's the last one defeated. */
export function beatenBlind(frame: ReplayFrame): string | null {
  if (frame.blind?.key) return frame.blind.name;
  const row = frame.blinds ?? {};
  const beaten = (["small", "big", "boss"] as const).filter((slot) => row[slot]?.status === "DEFEATED");
  return beaten.length ? (row[beaten.at(-1)!]?.name ?? null) : null;
}

/** The round's end: the blind beaten, and what cashing out pays. */
export function RoundEval({ frame }: { frame: ReplayFrame }) {
  const paid = frame.outcome?.cash_out;
  const beaten = beatenBlind(frame);
  return (
    <div className="screen round-eval">
      <h3>{beaten ? `${beaten} defeated` : "Round won"}</h3>
      <p>Score {num(frame.chips)}</p>
      {paid != null && <p className="money">Cash out ${num(paid)}</p>}
    </div>
  );
}

export function GameOver({ frame }: { frame: ReplayFrame }) {
  return (
    <div className="screen game-over">
      <h3>Game over</h3>
      <p>
        Ante {frame.ante} · Round {frame.round}
      </p>
    </div>
  );
}
