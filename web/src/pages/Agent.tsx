import { Link, useParams, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { useAgent, useAgentEpisodes, useTracks } from "../api/hooks";
import { Histogram } from "../components/Histogram";
import { StatTile } from "../components/Stats";
import { runRule, TrackTabs } from "../components/TrackTabs";
import { ago, endReason, fixed, interval, pct } from "../lib/format";

export function AgentPage({ mine = false }: { mine?: boolean }) {
  const { slug = "" } = useParams();
  const [params] = useSearchParams();
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
  const key = params.get("track") ?? tracks?.[0]?.key ?? Object.keys(data.tracks)[0] ?? "red-1";
  const t = tracks?.find((x) => x.key === key);
  const s = data.tracks[key];
  const hist = data.histogram[key] ?? [];
  const k = t?.episodes_per_agent ?? 500;
  const rows = episodes.data?.pages.flatMap((p) => p.episodes) ?? [];
  const several = (tracks?.length ?? 1) > 1;
  const margin = s?.blinds_ci95 ? (s.blinds_ci95[1]! - s.blinds_ci95[0]!) / 2 : null;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{a.name}</h1>
          <p className="muted">
            {a.kind === "house" ? "Baseline" : `by ${a.owner.login}`} · <code>{a.slug}</code>
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

      {tracks && <TrackTabs tracks={tracks} active={key} to={(x) => `?track=${encodeURIComponent(x)}`} />}
      {t && <p className="muted small rule">{runRule(t)}</p>}
      <section className="panel" aria-label="Results">
        {s ? (
          <>
            <div className="tiles">
              <StatTile
                label="Score"
                value={
                  <>
                    {fixed(s.blinds_mean)}
                    {margin != null && <span className="margin"> ±{fixed(margin)}</span>}
                  </>
                }
                sub={
                  <>
                    blinds beaten per run · <Link to="/docs#scoring">how it works</Link>
                  </>
                }
              />
              <StatTile
                label="Runs"
                value={s.n}
                sub={a.kind === "house" ? "a baseline: not ranked" : s.n >= k ? `all ${k} played` : `of ${k}, still playing`}
              />
              <StatTile label="Best ante" value={s.max_ante} sub={`${fixed(s.ante_mean)} on average`} />
              <StatTile
                label="Wins"
                value={pct(s.win_rate, s.win_rate ? 1 : 0)}
                sub={s.win_rate ? `likely ${interval(s.win_ci95, 1, true)}` : `of ${s.n} runs`}
              />
            </div>
            <Histogram counts={hist} title="Runs by blinds beaten" />
          </>
        ) : (
          <p className="muted">No ended runs on this track yet.</p>
        )}
      </section>

      <section className="panel" aria-label="Runs">
        <h2>Runs</h2>
        {rows.length === 0 ? (
          <p className="muted">No ended runs yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  {several && <th>Track</th>}
                  <th>Result</th>
                  <th className="num">Blinds</th>
                  <th className="num">Ante</th>
                  <th className="num">Actions</th>
                  <th>Ended</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => {
                  const won = e.final?.won;
                  return (
                    <tr key={e.id}>
                      <td>
                        <Link to={`/episodes/${e.id}${mine ? "?mine=1" : ""}`}>
                          <code>{e.id.slice(0, 8)}</code>
                        </Link>
                        {e.final?.verified === false && (
                          <span className="badge bad" title="Its replay didn't reach the recorded state">
                            unverified
                          </span>
                        )}
                      </td>
                      {several && <td className="small">{tracks?.find((x) => x.key === e.track)?.name ?? e.track}</td>}
                      <td>
                        <span className={`badge ${won ? "good" : ""}`}>{endReason(e.final?.end_reason)}</span>
                      </td>
                      <td className="num">{e.final?.rounds_beaten ?? "-"}</td>
                      <td className="num">{e.final?.ante_reached ?? "-"}</td>
                      <td className="num">{e.t}</td>
                      <td className="small muted">{ago(e.ended_at)}</td>
                    </tr>
                  );
                })}
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
