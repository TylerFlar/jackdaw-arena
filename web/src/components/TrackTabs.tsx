import { Link } from "react-router";
import { useNames } from "../api/catalog";
import type { TrackInfo } from "../api/client";
import { Icon } from "../art/Icon";

/** "Red Deck · White Stake": a track by its deck and stake, as the game names them. */
export function useTrackLabel() {
  const names = useNames();
  return (t: TrackInfo) => {
    const deck = names.info(t.back)?.name;
    const stake = names.stake(t.stake)?.name;
    return deck && stake ? `${deck} · ${stake}` : t.name;
  };
}

/** The tracks as tabs (links, so the track is in the URL): one tab while there's one track. */
export function TrackTabs({ tracks, active, to }: { tracks: TrackInfo[]; active: string; to: (key: string) => string }) {
  const names = useNames();
  const label = useTrackLabel();
  return (
    <nav className="tabs" aria-label="Tracks">
      {tracks.map((t) => (
        <Link key={t.key} to={to(t.key)} className="tab" aria-current={t.key === active ? "page" : undefined}>
          <Icon atlas="centers" entry={names.info(t.back)} />
          <Icon atlas="stakes" entry={names.stake(t.stake)} />
          {label(t)}
        </Link>
      ))}
    </nav>
  );
}

/** The track's rule, in a line. */
export function runRule(t: TrackInfo): string {
  const steps = t.max_steps.toLocaleString("en");
  return t.end_on_win
    ? `A run ends with a win, a loss, or after ${steps} actions.`
    : `A run ends with a loss or after ${steps} actions.`;
}
