import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import type { Frame, Leaderboard, MeDoc, Stats } from "../api/client";

export const ORIGIN = globalThis.location?.origin ?? "http://localhost:3000";
export const url = (path: string) => `${ORIGIN}${path}`;

export const stats = (over: Partial<Stats> = {}): Stats => ({
  n: 500, blinds_mean: 4.52, blinds_sem: 0.13, blinds_ci95: [4.27, 4.77], ante_mean: 2.08,
  max_ante: 8, win_rate: 0, win_ci95: [0, 0.0076], length_mean: 64.7, truncated: 0,
  forfeited: 0, unverified: 0, ...over,
}); // prettier-ignore

const agent = (slug: string, kind = "user") => ({
  slug, name: slug.toUpperCase(), description: "", url: null, kind,
  owner: { login: kind === "house" ? "jackdaw-house" : "ada", avatar_url: null },
  created_at: "2026-10-01T00:00:00Z",
}); // prettier-ignore

export const board: Leaderboard = {
  track: "red-1", season: "0.2.0", k: 500,
  ranked: [
    { rank: 1, agent: agent("ppo-big"), stats: stats({ blinds_mean: 5.9, blinds_ci95: [5.6, 6.2] }) },
    { rank: 2, agent: agent("ppo-demo"), stats: stats() },
  ],
  provisional: [{ rank: null, agent: agent("newcomer"), stats: stats({ n: 37, blinds_mean: 3.1 }) }],
  house: [{ rank: null, agent: agent("house-smart", "house"), stats: stats({ blinds_mean: 4.98 }) }],
}; // prettier-ignore

const card = (rank: string, suit: string, over = {}) => ({
  face_down: false, key: "c_base", front: `${suit[0]}_${rank[0]}`, suit, rank, edition: null,
  seal: null, debuff: false, cost: 1, sell_cost: 1, eternal: false, perishable: false,
  rental: false, ...over,
}); // prettier-ignore

export function frame(i: number, over: Partial<Frame> = {}): Frame {
  return {
    i, phase: i === 0 ? "blind_select" : "selecting_hand", ante: 1, round: 1, dollars: 4,
    chips: i * 10, hands_left: 4, discards_left: 3,
    blind: i === 0 ? null : { key: "bl_small", name: "Small Blind", chips: 300, boss: false, disabled: false, dollars: 3 },
    blinds: i === 0 ? { small: { name: "Small Blind", status: "SELECT", score: 300, tag: "Juggle Tag" } } : null,
    hand: i === 0 ? [] : [card("King", "Spades"), card("Ace", "Hearts", { seal: "Gold" })],
    jokers: [{ ...card("", "", { key: "j_joker", suit: null, rank: null, front: null }) }],
    consumables: [], shop: { cards: [], vouchers: [], boosters: [] }, pack: [], tags: [],
    last_score: null, deck_size: 44, discard_size: 0,
    action: i < 3 ? ["SelectBlind"] : null,
    description: i === 0 ? "Select Small Blind" : i === 1 ? "Play K♠ A♥" : i === 2 ? "Discard K♠" : null,
    ...over,
  }; // prettier-ignore
}

const atlas = (file: string, cols: number, rows: number, w = 142, h = 190) => ({
  file, cell: [w, h], size: [cols * w, rows * h],
}); // prettier-ignore

/** What infra/scripts/extract_art.py writes, for tests of the art path. */
export const artManifest = {
  version: 1, game: "1.0.1o", font: "m6x11plus.ttf", credit: "Balatro art © LocalThunk.",
  atlases: {
    cards: atlas("cards.png", 13, 4), centers: atlas("centers.png", 7, 5), jokers: atlas("jokers.png", 10, 16),
    tarots: atlas("tarots.png", 10, 6), vouchers: atlas("vouchers.png", 9, 4), boosters: atlas("boosters.png", 4, 9),
    stickers: atlas("stickers.png", 5, 3), tags: atlas("tags.png", 6, 5, 68, 68),
    stakes: atlas("stakes.png", 5, 2, 58, 58), blinds: atlas("blinds.png", 1, 31, 68, 68),
  },
}; // prettier-ignore

export const me: MeDoc = {
  user: { login: "ada", name: "Ada", avatar_url: null, is_admin: false },
  agents: [{
    ...agent("ppo-demo"), unlisted: false, hidden: false, used: { "red-1": 12 },
    tokens: [{ id: "t-1", prefix: "jdk_abc123", label: "laptop", created_at: "2026-10-20T00:00:00Z", last_used_at: null }],
  }],
  limits: { agents: 5, tokens_per_agent: 3 },
}; // prettier-ignore

export const handlers = [
  http.get(url("/api/version"), () => HttpResponse.json({ arena: "0.1.0", engine: "0.2.0", build: "test" })),
  http.get(url("/api/tracks"), () =>
    HttpResponse.json([{ key: "red-1", name: "Red Deck, White Stake", back: "b_red", stake: 1, max_steps: 2000,
      end_on_win: true, max_free_moves: 10, episodes_per_agent: 500 }]),  // prettier-ignore
  ),
  http.get(url("/api/leaderboard"), () => HttpResponse.json(board)),
  http.get(url("/auth/providers"), () => HttpResponse.json([{ id: "github", name: "GitHub" }])),
  http.get(url("/auth/session"), () => HttpResponse.json({ user: null })),
  http.get(url("/api/me"), () => HttpResponse.json({ error: "unauthorized", message: "sign in" }, { status: 401 })),
  http.get(url("/api/catalog"), () =>
    HttpResponse.json({ engine_version: "0.2.0", centers: { j_joker: { name: "Joker", set: "Joker", rarity: 1 } },
      blinds: { bl_small: { name: "Small Blind", boss: false } }, tags: {} }),  // prettier-ignore
  ),
  // No art by default: the site draws plain cards, as it does in CI and on forks.
  http.get(url("/art/v1/manifest.json"), () => new HttpResponse(null, { status: 404 })),
  http.get(url("/api/episodes/:id/frames"), ({ request }) => {
    const from = Number(new URL(request.url).searchParams.get("from") ?? 0);
    const frames = [0, 1, 2, 3].filter((i) => i >= from).map((i) => frame(i));
    return HttpResponse.json({ total: 4, start: from, frames });
  }),
];

export const server = setupServer(...handlers);

export function renderAt(path: string, routes: { path: string; element: ReactElement }[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          {routes.map((r) => (
            <Route key={r.path} path={r.path} element={r.element} />
          ))}
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
