import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { AccountPage } from "./pages/Account";
import { AgentPage } from "./pages/Agent";
import { GetStartedPage } from "./pages/GetStarted";
import { LeaderboardPage } from "./pages/Leaderboard";
import { NotFoundPage, SignInPage } from "./pages/SignIn";

// Replays bring the board and its animation library: a chunk of their own.
const EpisodePage = lazy(() => import("./pages/Episode").then((m) => ({ default: m.EpisodePage })));

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<LeaderboardPage />} />
        <Route path="/agents/:slug" element={<AgentPage />} />
        <Route path="/me/agents/:slug" element={<AgentPage mine />} />
        <Route
          path="/episodes/:id"
          element={
            <Suspense fallback={<p className="muted">Loading…</p>}>
              <EpisodePage />
            </Suspense>
          }
        />
        <Route path="/docs" element={<GetStartedPage />} />
        <Route path="/me" element={<AccountPage />} />
        <Route path="/signin" element={<SignInPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Layout>
  );
}
