import { Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { AccountPage } from "./pages/Account";
import { AgentPage } from "./pages/Agent";
import { EpisodePage } from "./pages/Episode";
import { GetStartedPage } from "./pages/GetStarted";
import { LeaderboardPage } from "./pages/Leaderboard";
import { NotFoundPage, SignInPage } from "./pages/SignIn";

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<LeaderboardPage />} />
        <Route path="/agents/:slug" element={<AgentPage />} />
        <Route path="/me/agents/:slug" element={<AgentPage mine />} />
        <Route path="/episodes/:id" element={<EpisodePage />} />
        <Route path="/docs" element={<GetStartedPage />} />
        <Route path="/me" element={<AccountPage />} />
        <Route path="/signin" element={<SignInPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Layout>
  );
}
