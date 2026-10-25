import { Link, useParams, useSearchParams } from "react-router";
import { useNames } from "../api/catalog";
import { ApiError, type Final } from "../api/client";
import { useEpisode, useTracks } from "../api/hooks";
import { DeckBack } from "../art/art";
import { Icon } from "../art/Icon";
import { ReplayViewer } from "../components/replay/ReplayViewer";
import { useTrackLabel } from "../components/TrackTabs";
import { endReason } from "../lib/format";

const VERIFIED =
  "The server replayed the seed and the tape with jackdaw, on its own, and reached the state it had recorded.";

/** "Lost · Ante 3 · 8 blinds". */
function headline(final: Final): string {
  const reason = endReason(final.end_reason);
  const blinds = final.rounds_beaten;
  return [
    reason.charAt(0).toUpperCase() + reason.slice(1),
    final.ante_reached != null && `Ante ${final.ante_reached}`,
    blinds != null && `${blinds} ${blinds === 1 ? "blind" : "blinds"}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function EpisodePage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const mine = params.get("mine") === "1";
  const { data: ep, error, isLoading } = useEpisode(id, mine);
  const { data: tracks } = useTracks();
  const names = useNames();
  const label = useTrackLabel();

  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="panel">
        <h1>No such episode</h1>
        <p className="muted">It doesn't exist, or it belongs to an unlisted agent.</p>
      </div>
    );
  }
  if (isLoading) return <p className="muted">Loading…</p>;
  if (!ep) return <p className="error">The episode couldn't load.</p>;

  const final = ep.final;
  const track = tracks?.find((t) => t.key === ep.track);

  return (
    <>
      <header className="episode-head">
        <p className="muted small crumbs">
          <Link to={`/agents/${ep.agent}`}>{ep.agent}</Link> ·{" "}
          {track ? (
            <span className="track-label">
              <Icon atlas="centers" entry={names.info(track.back)} />
              <Icon atlas="stakes" entry={names.stake(track.stake)} />
              {label(track)}
            </span>
          ) : (
            ep.track
          )}
        </p>
        <h1>{final ? headline(final) : `Episode ${id.slice(0, 8)}`}</h1>
        {final && (
          <p className="row small">
            <span className="muted">{final.length} actions</span>
            {final.verified ? (
              <span className="badge good" title={VERIFIED}>
                ✓ Verified
              </span>
            ) : (
              <span className="badge bad" title="Replaying the tape didn't reach the state the server recorded.">
                ✗ Not verified
              </span>
            )}
          </p>
        )}
      </header>

      {ep.status === "running" && (
        <div className="notice">
          This episode is still being played ({ep.t} steps so far). Its seed and replay are published
          when it ends.
        </div>
      )}

      {final && (
        <DeckBack.Provider value={track?.back ?? "b_red"}>
          <ReplayViewer episodeId={id} mine={mine} />
        </DeckBack.Provider>
      )}

      {final && (
        <details className="panel run-details">
          <summary>Run details</summary>
          <dl>
            <dt>Seed</dt>
            <dd>
              <code>{final.seed}</code>
            </dd>
            <dt>Final state</dt>
            <dd className="hash">{final.final_state_hash}</dd>
            <dt>Played with</dt>
            <dd>jackdaw {ep.engine_version}</dd>
            <dt>Episode</dt>
            <dd>
              <code>{ep.id}</code>
            </dd>
          </dl>
        </details>
      )}
    </>
  );
}
