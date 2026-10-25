import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { CardModel } from "../api/client";
import { artManifest, server, url } from "../test/server";
import { GameCard } from "./PlayingCard";

const base: CardModel = {
  face_down: false,
  key: "c_base",
  front: "H_A",
  suit: "Hearts",
  rank: "Ace",
  edition: null,
  seal: null,
  debuff: false,
  cost: 1,
  sell_cost: 1,
  eternal: false,
  perishable: false,
  rental: false,
};

function show(card: CardModel) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GameCard card={card} />
    </QueryClientProvider>,
  );
}

describe("cards", () => {
  it("draws a playing card with its rank, suit and seal", async () => {
    show({ ...base, seal: "Gold", key: "m_glass" });
    const name = "A♥ (Glass), Gold seal";
    await waitFor(() => expect(screen.getByRole("img", { name })).toHaveClass("pcard", "red", "glass"));
    expect(screen.getByRole("img", { name })).toHaveTextContent("A♥");
  });

  it("keeps face-down cards hidden", async () => {
    show({ ...base, face_down: true, rank: null, suit: null });
    await waitFor(() => expect(screen.getByRole("img", { name: "face-down card" })).toHaveClass("down"));
  });

  it("names jokers from the catalog and links the wiki", async () => {
    show({ ...base, key: "j_joker", rank: null, suit: null, front: null, edition: "foil" });
    const link = await screen.findByRole("link", { name: "Joker" });
    expect(link).toHaveAttribute("href", "https://balatrowiki.org/w/Joker");
    expect(screen.getByText(/Joker · foil/)).toBeInTheDocument();
  });

  it("draws Balatro's sprites when the site has them", async () => {
    server.use(
      http.get(url("/art/v1/manifest.json"), () => HttpResponse.json(artManifest)),
      http.get(url("/api/catalog"), () =>
        HttpResponse.json({ engine_version: "0.2.1", centers: { c_base: { name: "Base Card", set: "Default", pos: [1, 0] } },
          blinds: {}, tags: {}, stakes: {} }), // prettier-ignore
      ),
    );
    show({ ...base, seal: "Gold" });
    const name = "A♥, Gold seal";
    await waitFor(() => expect(screen.getByRole("img", { name }).querySelector(".sprite")).not.toBeNull());
    const card = screen.getByRole("img", { name });
    expect(card).toHaveClass("gcard");
    const [blank, face, seal] = card.querySelectorAll<HTMLElement>(".sprite");
    expect(blank!.style.backgroundImage).toContain("/art/v1/centers.png");
    expect(face!.style.backgroundImage).toContain("/art/v1/cards.png");
    expect(face!.style.backgroundPosition).toBe("100% 0%"); // the ace column, the hearts row
    expect(face!.style.backgroundSize).toBe("1300% 400%");
    expect(seal!.style.backgroundPosition).toBe("33.33333333333333% 0%");
  });
});
