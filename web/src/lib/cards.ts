import type { CardModel } from "../api/client";

const RANK: Record<string, string> = { Jack: "J", Queen: "Q", King: "K", Ace: "A" };
const SUIT: Record<string, string> = { Hearts: "♥", Diamonds: "♦", Clubs: "♣", Spades: "♠" };

export function rankLabel(rank: string | null | undefined): string {
  return rank ? (RANK[rank] ?? rank) : "";
}

export function suitGlyph(suit: string | null | undefined): string {
  return suit ? (SUIT[suit] ?? suit.charAt(0)) : "";
}

export function isRed(suit: string | null | undefined): boolean {
  return suit === "Hearts" || suit === "Diamonds";
}

export function isPlayingCard(c: CardModel): boolean {
  return Boolean(c.rank && c.suit);
}

/** Enhancement keys (m_glass...) as words; c_base is a plain card. */
export function enhancement(key: string | null | undefined): string | null {
  if (!key || key === "c_base" || !key.startsWith("m_")) return null;
  const word = key.slice(2);
  return word.charAt(0).toUpperCase() + word.slice(1);
}

export function cardText(c: CardModel, names: (key: string) => string): string {
  if (c.face_down) return "face-down card";
  if (isPlayingCard(c)) return `${rankLabel(c.rank)}${suitGlyph(c.suit)}`;
  return c.key ? names(c.key) : "?";
}

export function wikiUrl(name: string): string {
  return `https://balatrowiki.org/w/${encodeURIComponent(name.replace(/ /g, "_"))}`;
}
