import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CardModel } from "../api/client";
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
  it("draws a playing card with its rank, suit and seal", () => {
    show({ ...base, seal: "Gold", key: "m_glass" });
    const card = screen.getByRole("img", { name: "A♥ (Glass), Gold seal" });
    expect(card).toHaveClass("pcard", "red", "glass");
    expect(card).toHaveTextContent("A♥");
  });

  it("keeps face-down cards hidden", () => {
    show({ ...base, face_down: true, rank: null, suit: null });
    expect(screen.getByRole("img", { name: "face-down card" })).toHaveClass("down");
  });

  it("names jokers from the catalog and links the wiki", async () => {
    show({ ...base, key: "j_joker", rank: null, suit: null, front: null, edition: "foil" });
    const link = await screen.findByRole("link", { name: "Joker" });
    expect(link).toHaveAttribute("href", "https://balatrowiki.org/w/Joker");
    expect(screen.getByText(/Joker · foil/)).toBeInTheDocument();
  });
});
