import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { board, renderAt, server, url } from "../test/server";
import { LeaderboardPage } from "./Leaderboard";

const routes = [{ path: "/", element: <LeaderboardPage /> }];

describe("leaderboard", () => {
  it("ranks agents by score, with the baselines among them unranked", async () => {
    renderAt("/", routes);
    const standings = await screen.findByRole("region", { name: "Standings" });
    const [, finished] = within(standings).getAllByRole("rowgroup");
    const rows = within(finished!).getAllByRole<HTMLTableRowElement>("row");
    expect(rows.map((r) => within(r).getAllByRole("link")[0]!.textContent)).toEqual(["PPO-BIG", "HOUSE-SMART", "PPO-DEMO"]);
    expect(rows.map((r) => r.cells[0]!.textContent)).toEqual(["1", "–", "2"]);
    expect(within(rows[1]!).getByText("Baseline")).toBeInTheDocument();
    // The score, and its 95% margin of error: half the interval.
    expect(within(rows[0]!).getByText("5.90")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("±0.30")).toBeInTheDocument();
    expect(rows[0]!.cells[2]).toHaveAttribute("title", "95% range 5.60 – 6.20, 500 runs");
  });

  it("lists agents still playing under In progress, with how far they've got", async () => {
    renderAt("/", routes);
    const group = await screen.findByRole("rowheader", { name: "In progress" });
    const rows = within(group.closest("tbody")!).getAllByRole("row");
    expect(within(rows[1]!).getByRole("link", { name: "NEWCOMER" })).toBeInTheDocument();
    expect(within(rows[1]!).getByRole("progressbar", { name: "37 of 500 runs" })).toHaveAttribute("value", "37");
  });

  it("explains the score and shows the track as a tab", async () => {
    renderAt("/", routes);
    const help = await screen.findByRole("link", { name: /How scores work/ });
    expect(help).toHaveAttribute("href", "/docs#scoring");
    const tabs = await screen.findByRole("navigation", { name: "Tracks" });
    expect(within(tabs).getByRole("link", { name: "Red Deck, White Stake" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("A run ends with a win, a loss, or after 2,000 actions.")).toBeInTheDocument();
  });

  it("shows the player-view track as a tab of its own, with what its agents see", async () => {
    const red = { key: "red-1", name: "Red Deck, White Stake", back: "b_red", stake: 1, max_steps: 2000,
      end_on_win: true, max_free_moves: 10, episodes_per_agent: 500, player_view: false }; // prettier-ignore
    const pv = { ...red, key: "red-1-pv", name: "Red Deck, White Stake, player view", player_view: true };
    server.use(http.get(url("/api/tracks"), () => HttpResponse.json([red, pv])));
    renderAt("/?track=red-1-pv", routes);
    const tabs = await screen.findByRole("navigation", { name: "Tracks" });
    expect(within(tabs).getByRole("link", { name: red.name })).not.toHaveAttribute("aria-current");
    expect(within(tabs).getByRole("link", { name: pv.name })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText(/Agents see jackdaw's player view: no card a player hasn't seen\./)).toBeInTheDocument();
  });

  it("explains an empty board", async () => {
    server.use(
      http.get(url("/api/leaderboard"), () => HttpResponse.json({ ...board, ranked: [], provisional: [], house: [] })),
    );
    renderAt("/", routes);
    expect(await screen.findByText(/No agent has finished its 500 runs yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Be the first." })).toHaveAttribute("href", "/docs");
    expect(screen.queryByRole("table")).toBeNull();
  });
});
