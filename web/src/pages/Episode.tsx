import { Link, useParams, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { useEpisode, useTracks } from "../api/hooks";
import { ReplayViewer } from "../components/replay/ReplayViewer";
import { endReason } from "../lib/format";

export function EpisodePage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const mine = params.get("mine") === "1";
  const { data: ep, error, isLoading } = useEpisode(id, mine);
  const { data: tracks } = useTracks();

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

  const final = ep?.final;
  const trackName = tracks?.find((t) => t.key === ep.track)?.name ?? ep.track;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>
            Episode <code>{id.slice(0, 8)}</code>
          </h1>
          {ep && (
            <p className="muted">
              <Link to={`/agents/${ep.agent}`}>{ep.agent}</Link> · {trackName}
            </p>
          )}
        </div>
      </div>

      {ep?.status === "running" && (
        <div className="notice">
          This episode is still being played ({ep.t} steps so far). Its seed and replay are published
          when it ends.
        </div>
      )}

      {final && (
        <section className="panel">
          <div className="tiles" style={{ marginBottom: "0.75rem" }}>
            <Tile label="Result" value={endReason(final.end_reason)} />
            <Tile label="Blinds beaten" value={String(final.rounds_beaten ?? "-")} />
            <Tile label="Ante reached" value={String(final.ante_reached ?? "-")} />
            <Tile label="Steps" value={String(final.length)} />
          </div>
          <div className="row small">
            {final.verified ? (
              <span className="badge good">✓ verified by replay</span>
            ) : (
              <span className="badge bad">✗ not verified</span>
            )}
            <span className="muted">seed</span> <code>{final.seed}</code>
            <span className="muted">state hash</span> <span className="hash">{final.final_state_hash}</span>
          </div>
        </section>
      )}

      {final && <ReplayViewer episodeId={id} mine={mine} />}
    </>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value" style={{ fontSize: "1.25rem" }}>
        {value}
      </div>
    </div>
  );
}
