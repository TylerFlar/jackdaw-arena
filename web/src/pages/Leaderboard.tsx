import { Link, useSearchParams } from "react-router";
import type { BoardRow, Leaderboard } from "../api/client";
import { useLeaderboard, useTracks } from "../api/hooks";
import { runRule, TrackTabs } from "../components/TrackTabs";
import { ago, fixed, interval, pct } from "../lib/format";

const SCORE_HELP = "Average blinds beaten per run: higher is better. ± is the 95% margin of error.";

export function LeaderboardPage() {
  const [params] = useSearchParams();
  const { data: tracks } = useTracks();
  const track = params.get("track") ?? tracks?.[0]?.key ?? "red-1";
  const { data: board, isLoading, error, isPlaceholderData } = useLeaderboard(track);
  const info = tracks?.find((t) => t.key === track);

  return (
    <>
      <h1>Leaderboard</h1>
      {tracks && <TrackTabs tracks={tracks} active={track} to={(key) => `/?track=${encodeURIComponent(key)}`} />}
      {info && <p className="muted small rule">{runRule(info)}</p>}
      {error && <p className="error">The leaderboard couldn't load. Try again in a moment.</p>}
      {isLoading && <p className="muted">Loading…</p>}
      {board && <Standings board={board} dim={isPlaceholderData} />}
    </>
  );
}

const byScore = (a: BoardRow, b: BoardRow) =>
  b.stats.blinds_mean - a.stats.blinds_mean || a.agent.slug.localeCompare(b.agent.slug);

function Standings({ board, dim }: { board: Leaderboard; dim: boolean }) {
  // Baselines sit among the ranked agents, by score, so it's plain where an agent lands.
  const finished = [...board.ranked, ...board.house].sort(byScore);
  return (
    <section className="panel" aria-label="Standings" style={{ opacity: dim ? 0.5 : 1 }}>
      {board.ranked.length === 0 && (
        <p className="muted">
          No agent has finished its {board.k} runs yet. <Link to="/docs">Be the first.</Link>
        </p>
      )}
      {(finished.length > 0 || board.provisional.length > 0) && (
        <div className="table-wrap">
          <table className="standings">
            <thead>
              <tr>
                <th scope="col" className="rank">
                  Rank
                </th>
                <th scope="col">Agent</th>
                <th scope="col" className="num">
                  Score{" "}
                  <Link to="/docs#scoring" className="help" title={SCORE_HELP} aria-label={`How scores work. ${SCORE_HELP}`}>
                    ?
                  </Link>
                </th>
                <th scope="col" className="num">
                  Runs
                </th>
                <th scope="col" className="num opt">
                  Best ante
                </th>
                <th scope="col" className="num opt">
                  Wins
                </th>
                <th scope="col" className="num opt">
                  Last played
                </th>
              </tr>
            </thead>
            <tbody>
              {finished.map((r) => (
                <Row key={r.agent.slug} row={r} k={board.k} />
              ))}
            </tbody>
            {board.provisional.length > 0 && (
              <tbody>
                <tr className="group">
                  <th scope="rowgroup" colSpan={7}>
                    In progress
                  </th>
                </tr>
                {board.provisional.map((r) => (
                  <Row key={r.agent.slug} row={r} k={board.k} playing />
                ))}
              </tbody>
            )}
          </table>
        </div>
      )}
    </section>
  );
}

function Row({ row, k, playing = false }: { row: BoardRow; k: number; playing?: boolean }) {
  const { agent, stats: s } = row;
  const baseline = agent.kind === "house";
  const ci = s.blinds_ci95;
  const margin = ci ? (ci[1]! - ci[0]!) / 2 : null;
  const range = `${ci ? `95% range ${interval(ci)}, ` : ""}${s.n} runs`;
  return (
    <tr className={baseline ? "baseline" : undefined}>
      <td className="rank">{row.rank ? <span className={`place p${Math.min(row.rank, 4)}`}>{row.rank}</span> : "–"}</td>
      <td>
        <div className="agent-cell">
          {agent.owner.avatar_url ? (
            <img className="avatar" src={agent.owner.avatar_url} alt="" />
          ) : (
            <span className="avatar" aria-hidden="true" />
          )}
          <div className="who">
            <Link to={`/agents/${agent.slug}`}>{agent.name}</Link>
            {baseline ? (
              <span>
                <span className="badge" title={agent.description || undefined}>
                  Baseline
                </span>
              </span>
            ) : (
              <span className="muted small">{agent.owner.login}</span>
            )}
          </div>
          {s.unverified > 0 && (
            <span className="badge bad" title="Runs whose replay didn't verify">
              {s.unverified} unverified
            </span>
          )}
        </div>
      </td>
      <td className="num" title={range}>
        <span className="score-value">{fixed(s.blinds_mean)}</span>
        {margin != null && <span className="margin"> ±{fixed(margin)}</span>}
      </td>
      <td className="num">
        {playing ? (
          <span className="progress-cell">
            <progress value={s.n} max={k} aria-label={`${s.n} of ${k} runs`} />
            {s.n} / {k}
          </span>
        ) : (
          s.n
        )}
      </td>
      <td className="num opt">{s.max_ante}</td>
      <td className="num opt">{pct(s.win_rate, s.win_rate ? 1 : 0)}</td>
      <td className="num opt">{ago(s.last_played)}</td>
    </tr>
  );
}
