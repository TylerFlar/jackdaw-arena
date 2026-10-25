import { useState } from "react";
import { Link } from "react-router";
import { ApiError, type MyAgent, type NewToken } from "../api/client";
import { useCreateAgent, useCreateToken, useMe, useRevokeToken, useUpdateAgent } from "../api/hooks";
import { CopyButton } from "../components/CopyButton";
import { SignInOptions } from "./SignIn";
import { ago } from "../lib/format";

export function AccountPage() {
  const { data: me, isLoading } = useMe();
  if (isLoading) return <p className="muted">Loading…</p>;
  if (!me) {
    return (
      <div className="panel">
        <h1>Your agents</h1>
        <p>Sign in to create agents and tokens.</p>
        <SignInOptions next="/me" />
      </div>
    );
  }
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Your agents</h1>
          <p className="muted">
            Signed in as {me.user.login}. Up to {me.limits.agents} agents, {me.limits.tokens_per_agent} tokens
            each.
          </p>
        </div>
      </div>
      {me.agents.map((a) => (
        <AgentCard key={a.slug} agent={a} />
      ))}
      {me.agents.length < (me.limits.agents ?? 5) && <NewAgent />}
    </>
  );
}

function NewAgent() {
  const create = useCreateAgent();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [url, setUrl] = useState("");
  const [unlisted, setUnlisted] = useState(false);
  const err = create.error instanceof ApiError ? create.error.message : create.error ? "Something went wrong" : null;
  return (
    <section className="panel">
      <h2>New agent</h2>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { slug, name, description, url: url || null, unlisted },
            { onSuccess: () => [setSlug, setName, setDescription, setUrl].forEach((f) => f("")) },
          );
        }}
      >
        <label>
          Slug (in its URL; 3-40 lowercase letters, digits and hyphens)
          <input type="text" value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} required pattern="[a-z0-9][a-z0-9-]{1,38}[a-z0-9]" />
        </label>
        <label>
          Name
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} required maxLength={60} />
        </label>
        <label>
          Description (method, training budget…)
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} rows={2} />
        </label>
        <label>
          Link (paper or code, optional)
          <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" />
        </label>
        <label className="inline">
          <input type="checkbox" checked={unlisted} onChange={(e) => setUnlisted(e.target.checked)} />
          Unlisted: keep it off the leaderboard and its replays private
        </label>
        {err && <p className="error">{err}</p>}
        <div>
          <button type="submit" className="primary" disabled={create.isPending}>
            Create agent
          </button>
        </div>
      </form>
    </section>
  );
}

function AgentCard({ agent }: { agent: MyAgent }) {
  const update = useUpdateAgent();
  const mint = useCreateToken();
  const revoke = useRevokeToken();
  const [label, setLabel] = useState("");
  const [fresh, setFresh] = useState<NewToken | null>(null);
  const used = Object.entries(agent.used);
  return (
    <section className="panel" aria-label={agent.name}>
      <div className="row">
        <h2 style={{ margin: 0 }}>
          <Link to={agent.unlisted ? `/me/agents/${agent.slug}` : `/agents/${agent.slug}`}>{agent.name}</Link>
        </h2>
        <code className="small muted">{agent.slug}</code>
        {agent.unlisted && <span className="badge">unlisted</span>}
        {agent.hidden && <span className="badge bad">hidden by a moderator</span>}
        <span className="spacer" />
        <label className="inline small">
          <input
            type="checkbox"
            checked={agent.unlisted}
            onChange={(e) => update.mutate({ slug: agent.slug, unlisted: e.target.checked })}
          />
          Unlisted
        </label>
      </div>
      <p className="small muted">
        {used.length ? used.map(([t, n]) => `${n} episodes on ${t}`).join(" · ") : "No episodes yet"}
      </p>

      <h3>Tokens</h3>
      {agent.tokens.length === 0 ? (
        <p className="muted small">No tokens. Mint one to let your code play as this agent.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Token</th>
              <th>Label</th>
              <th>Created</th>
              <th>Last used</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {agent.tokens.map((t) => (
              <tr key={t.id}>
                <td>
                  <code>{t.prefix}…</code>
                </td>
                <td>{t.label || <span className="muted">-</span>}</td>
                <td className="small">{ago(t.created_at)}</td>
                <td className="small">{t.last_used_at ? ago(t.last_used_at) : "never"}</td>
                <td>
                  <button type="button" className="danger" onClick={() => revoke.mutate(t.id)} disabled={revoke.isPending}>
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form
        className="row"
        style={{ marginTop: "0.5rem" }}
        onSubmit={(e) => {
          e.preventDefault();
          mint.mutate(
            { slug: agent.slug, label },
            {
              onSuccess: (token) => {
                setFresh(token);
                setLabel("");
              },
            },
          );
        }}
      >
        <input type="text" placeholder="label (e.g. laptop)" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={60} aria-label="Token label" />
        <button type="submit" disabled={mint.isPending}>
          New token
        </button>
        {mint.error instanceof ApiError && <span className="error small">{mint.error.message}</span>}
      </form>

      {fresh && (
        <div className="notice" role="region" aria-label="New token" style={{ marginTop: "0.75rem" }}>
          <h3>Your new token</h3>
          <p>This is the only time it is shown. Store it somewhere safe:</p>
          <p className="token" data-testid="new-token">
            {fresh.token}
          </p>
          <pre>{`mkdir -p ~/.jackdaw-arena && echo "${fresh.token}" > ~/.jackdaw-arena/token`}</pre>
          <div className="row">
            <CopyButton text={fresh.token} label="Copy token" />
            <button type="button" className="primary" onClick={() => setFresh(null)}>
              Done
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
