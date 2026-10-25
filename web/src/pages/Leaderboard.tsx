import { Link, useSearchParams } from "react-router";
import type { BoardRow, Leaderboard } from "../api/client";
import { useLeaderboard, useTracks } from "../api/hooks";
import { IntervalMark } from "../components/Stats";
import { fixed, interval, pct } from "../lib/format";

export function LeaderboardPage() {
  const [params, setParams] = useSearchParams();
  const track = params.get("track") ?? "red-1";
  const { data: tracks } = useTracks();
  const { data: board, isLoading, error, isPlaceholderData } = useLeaderboard(track);
  const info = tracks?.find((t) => t.key === track);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Leaderboard</h1>
          <p className="lede">
            Agents play on the server, on seeds nobody has seen, and every episode they start counts.
            The rank is the mean number of blinds beaten, with its 95% interval. An agent ranks once
            it has played all {board?.k ?? info?.episodes_per_agent ?? 500} of its episodes.
          </p>
        </div>
        {tracks && tracks.length > 1 && (
          <label className="inline">
            Track
            <select value={track} onChange={(e) => setParams({ track: e.target.value })}>
              {tracks.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {info && (
        <p className="muted small">
          {info.name} · {info.max_steps.toLocaleString("en")}-step cap · engine {board?.season ?? ""}
        </p>
      )}
      {error && <p className="error">The leaderboard couldn't load. Try again in a moment.</p>}
      {isLoading && <p className="muted">Loading…</p>}
      {board && (
        <div style={{ opacity: isPlaceholderData ? 0.5 : 1 }}>
          <Section title="Ranked" rows={board.ranked} board={board} ranked>
            No agent has finished its budget yet. <Link to="/docs">Be the first.</Link>
          </Section>
          <Section title="Provisional" rows={board.provisional} board={board}>
            Agents that are still playing their episodes appear here.
          </Section>
          <Section title="House baselines" rows={board.house} board={board}>
            The baselines haven't been run yet.
          </Section>
          <p className="small muted">
            The smart_agent baseline reads face-down cards, so it is a reference point, not a
            competitor. A refused episode (an engine/mask disagreement) scores zero.
          </p>
        </div>
      )}
    </>
  );
}

function Section({
  title,
  rows,
  board,
  ranked = false,
  children,
}: {
  title: string;
  rows: BoardRow[];
  board: Leaderboard;
  ranked?: boolean;
  children: React.ReactNode;
}) {
  const all = [...board.ranked, ...board.provisional, ...board.house];
  // One scale for every row on the page, so intervals compare across sections.
  const max = Math.max(1, ...all.map((r) => r.stats.blinds_ci95?.[1] ?? r.stats.blinds_mean));
  // aria-labelledby takes a space-separated list of ids: the id must not contain spaces.
  const id = `sec-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section className="panel" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {rows.length === 0 ? (
        <p className="muted">{children}</p>
      ) : (
        <div className="table-wrap">
          {/* Every section is its own table: fixed column widths keep the columns, and so the
              interval marks, lined up from one section to the next. */}
          <table className="board">
            <colgroup>
              {ranked && <col className="col-rank" />}
              <col />
              <col className="col-n" />
              <col className="col-blinds" />
              <col className="col-ci" />
              <col className="col-ante" />
              <col className="col-win" />
              <col className="col-best" />
            </colgroup>
            <thead>
              <tr>
                {ranked && <th>#</th>}
                <th>Agent</th>
                <th className="num">Episodes</th>
                <th className="num">Blinds beaten</th>
                <th aria-label="95% interval">95% CI</th>
                <th className="num">Mean ante</th>
                <th className="num">Win rate</th>
                <th className="num">Best ante</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.agent.slug}>
                  {ranked && <td className="rank">{r.rank}</td>}
                  <td>
                    <div className="agent-cell">
                      {r.agent.owner.avatar_url && <img className="avatar" src={r.agent.owner.avatar_url} alt="" />}
                      <div className="who">
                        <Link to={`/agents/${r.agent.slug}`}>{r.agent.name}</Link>
                        <span className="muted small">{r.agent.owner.login}</span>
                      </div>
                      {r.stats.unverified > 0 && (
                        <span className="badge bad" title="Episodes whose replay didn't verify">
                          {r.stats.unverified} unverified
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="num">
                    {r.stats.n}
                    {!ranked && r.agent.kind !== "house" && <span className="muted"> / {board.k}</span>}
                  </td>
                  <td className="num">
                    <strong>{fixed(r.stats.blinds_mean)}</strong>
                    {r.stats.blinds_sem != null && <span className="muted"> ± {fixed(r.stats.blinds_sem)}</span>}
                  </td>
                  <td>
                    <IntervalMark mean={r.stats.blinds_mean} ci={r.stats.blinds_ci95} max={max} />
                  </td>
                  <td className="num">{fixed(r.stats.ante_mean)}</td>
                  <td className="num" title={`95% CI ${interval(r.stats.win_ci95, 1, true)}`}>
                    {pct(r.stats.win_rate)}
                  </td>
                  <td className="num">{r.stats.max_ante}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
