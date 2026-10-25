import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { board, renderAt, server, url } from "../test/server";
import { LeaderboardPage } from "./Leaderboard";

const routes = [{ path: "/", element: <LeaderboardPage /> }];

describe("leaderboard", () => {
  it("shows ranked, provisional and house agents in their sections", async () => {
    renderAt("/", routes);
    const ranked = await screen.findByRole("region", { name: "Ranked" });
    const rows = within(ranked).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("link").textContent)).toEqual(["PPO-BIG", "PPO-DEMO"]);
    expect(within(rows[0]!).getByText("5.90")).toBeInTheDocument();
    expect(
      within(rows[0]!).getByRole("img", { name: /mean 5\.90, 95% CI 5\.60 to 6\.20/ }),
    ).toBeInTheDocument();
    const provisional = screen.getByRole("region", { name: "Provisional" });
    expect(within(provisional).getByText("/ 500")).toBeInTheDocument();
    const house = screen.getByRole("region", { name: "House baselines" });
    expect(within(house).getByText("HOUSE-SMART")).toBeInTheDocument();
  });

  it("lays every section on one column grid, so the interval marks line up", async () => {
    const { container } = renderAt("/", routes);
    await screen.findByRole("region", { name: "Ranked" });
    const grids = [...container.querySelectorAll("table")].map((t) => ({
      board: t.classList.contains("board"),
      cols: [...t.querySelectorAll("col")].map((c) => c.className),
    }));
    expect(grids).toHaveLength(3);
    const tail = ["", "col-n", "col-blinds", "col-ci", "col-ante", "col-win", "col-best"];
    expect(grids[0]).toEqual({ board: true, cols: ["col-rank", ...tail] });
    expect(grids.slice(1)).toEqual([
      { board: true, cols: tail },
      { board: true, cols: tail },
    ]);
  });

  it("explains an empty board", async () => {
    server.use(
      http.get(url("/api/leaderboard"), () =>
        HttpResponse.json({ ...board, ranked: [], provisional: [], house: [] }),
      ),
    );
    renderAt("/", routes);
    expect(await screen.findByText(/No agent has finished its budget yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Be the first." })).toHaveAttribute("href", "/docs");
  });
});
