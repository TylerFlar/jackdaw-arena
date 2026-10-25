import { Link, useParams } from "react-router";
import { ApiError } from "../api/client";
import { useAgent, useAgentEpisodes, useTracks } from "../api/hooks";
import { Histogram } from "../components/Histogram";
import { StatTile } from "../components/Stats";
import { ago, endReason, fixed, interval, pct } from "../lib/format";

export function AgentPage({ mine = false }: { mine?: boolean }) {
  const { slug = "" } = useParams();
  const { data, error, isLoading } = useAgent(slug, mine);
  const { data: tracks } = useTracks();
  const episodes = useAgentEpisodes(slug, mine);

  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="panel">
        <h1>No such agent</h1>
        <p className="muted">It doesn't exist, or its owner keeps it unlisted.</p>
      </div>
    );
  }
  if (isLoading || !data) return <p className="muted">Loading…</p>;

  const a = data.agent;
  const trackKeys = Object.keys(data.tracks);
  const rows = episodes.data?.pages.flatMap((p) => p.episodes) ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{a.name}</h1>
          <p className="muted">
            {a.kind === "house" ? "House baseline" : `by ${a.owner.login}`} · <code>{a.slug}</code>
            {a.url && (
              <>
                {" "}
                · <a href={a.url}>code</a>
              </>
            )}
          </p>
          {a.description && <p className="lede">{a.description}</p>}
        </div>
      </div>

      {trackKeys.map((key) => {
        const s = data.tracks[key];
        const t = tracks?.find((x) => x.key === key);
        const hist = data.histogram[key] ?? [];
        return (
          <section key={key} className="panel" aria-label={t?.name ?? key}>
            <h2>{t?.name ?? key}</h2>
            {s ? (
              <>
                <div className="tiles">
                  <StatTile
                    label="Blinds beaten"
                    value={fixed(s.blinds_mean)}
                    sub={s.blinds_ci95 ? `95% CI ${interval(s.blinds_ci95)}` : undefined}
                  />
                  <StatTile label="Episodes" value={s.n} sub={t ? `of ${t.episodes_per_agent} budgeted` : undefined} />
                  <StatTile label="Win rate" value={pct(s.win_rate)} sub={`95% CI ${interval(s.win_ci95, 1, true)}`} />
                  <StatTile label="Mean ante" value={fixed(s.ante_mean)} sub={`best ${s.max_ante}`} />
                </div>
                <Histogram counts={hist} title="Episodes by blinds beaten" />
              </>
            ) : (
              <p className="muted">No ended episodes on this track yet.</p>
            )}
          </section>
        );
      })}

      <section className="panel">
        <h2>Episodes</h2>
        {rows.length === 0 ? (
          <p className="muted">No ended episodes yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Episode</th>
                  <th>Ended</th>
                  <th>Result</th>
                  <th className="num">Blinds</th>
                  <th className="num">Ante</th>
                  <th className="num">Steps</th>
                  <th>Verified</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id}>
                    <td>
                      <Link to={`/episodes/${e.id}${mine ? "?mine=1" : ""}`}>
                        <code>{e.id.slice(0, 8)}</code>
                      </Link>
                    </td>
                    <td className="small muted">{ago(e.ended_at)}</td>
                    <td>{endReason(e.final?.end_reason)}</td>
                    <td className="num">{e.final?.rounds_beaten ?? "-"}</td>
                    <td className="num">{e.final?.ante_reached ?? "-"}</td>
                    <td className="num">{e.t}</td>
                    <td>{e.final?.verified ? <span className="badge good">✓ verified</span> : <span className="badge bad">no</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {episodes.hasNextPage && (
          <button type="button" onClick={() => episodes.fetchNextPage()} disabled={episodes.isFetchingNextPage}>
            {episodes.isFetchingNextPage ? "Loading…" : "Load more"}
          </button>
        )}
      </section>
    </>
  );
}
