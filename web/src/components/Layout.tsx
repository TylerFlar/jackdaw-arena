import type { ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router";
import { useMe, useProviders, useSignOut, useVersion } from "../api/hooks";

export function signInHref(provider: string, next: string): string {
  return `/auth/login/${encodeURIComponent(provider)}?next=${encodeURIComponent(next)}`;
}

function SignIn() {
  const { data: providers } = useProviders();
  const location = useLocation();
  const next = location.pathname + location.search;
  if (!providers?.length) return null;
  if (providers.length === 1) {
    const p = providers[0]!;
    // A full-page navigation: the sign-in round trip goes through the provider.
    return (
      <a className="button primary" href={signInHref(p.id, next)}>
        Sign in with {p.name}
      </a>
    );
  }
  return (
    <Link className="button primary" to={`/signin?next=${encodeURIComponent(next)}`}>
      Sign in
    </Link>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { data: me } = useMe();
  const { data: version } = useVersion();
  const signOut = useSignOut();
  return (
    <div className="shell">
      <header className="header">
        <div className="container">
          <Link className="brand" to="/">
            <span aria-hidden="true">♠</span> Jackdaw Arena
          </Link>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              Leaderboard
            </NavLink>
            <NavLink to="/docs">Get started</NavLink>
            {me && <NavLink to="/me">Your agents</NavLink>}
          </nav>
          <div className="user">
            {me ? (
              <>
                {me.user.avatar_url && <img className="avatar" src={me.user.avatar_url} alt="" />}
                <span className="small">{me.user.login}</span>
                <button type="button" onClick={() => signOut.mutate()}>
                  Sign out
                </button>
              </>
            ) : (
              <SignIn />
            )}
          </div>
        </div>
      </header>
      <main>
        <div className="container">{children}</div>
      </main>
      <footer className="footer">
        <div className="container">
          <span>
            Engine <a href="https://github.com/TylerFlar/jackdaw-balatro">jackdaw</a>{" "}
            {version?.engine ?? ""}
          </span>
          <a href="https://github.com/TylerFlar/jackdaw-arena">Source</a>
          <a href="/api/docs">API</a>
          <span>Not affiliated with LocalThunk or Playstack. No game assets are used.</span>
        </div>
      </footer>
    </div>
  );
}
