import { Link, useSearchParams } from "react-router";
import { useProviders } from "../api/hooks";
import { signInHref } from "../components/Layout";

export function SignInOptions({ next }: { next: string }) {
  const { data: providers, isLoading } = useProviders();
  if (isLoading) return <p className="muted">Loading…</p>;
  if (!providers?.length) return <p className="muted">Sign-in isn't set up on this server.</p>;
  return (
    <div className="row">
      {providers.map((p) => (
        <a key={p.id} className="button primary" href={signInHref(p.id, next)}>
          Sign in with {p.name}
        </a>
      ))}
    </div>
  );
}

export function SignInPage() {
  const [params] = useSearchParams();
  const error = params.get("error");
  const next = params.get("next") ?? "/me";
  return (
    <div className="panel" style={{ maxWidth: 560 }}>
      <h1>Sign in</h1>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <p className="muted">The Arena reads only your public profile (your login and avatar).</p>
      <SignInOptions next={next} />
    </div>
  );
}

export function NotFoundPage() {
  return (
    <div className="panel">
      <h1>Not found</h1>
      <p>
        That page doesn't exist. <Link to="/">Back to the leaderboard.</Link>
      </p>
    </div>
  );
}
