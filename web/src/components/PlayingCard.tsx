import type { CardModel } from "../api/client";
import { useNames } from "../api/catalog";
import { enhancement, isPlayingCard, isRed, rankLabel, suitGlyph, wikiUrl } from "../lib/cards";

/** A playing card in CSS (rank, suit glyph, enhancement, seal, edition), or a named tile for
 * anything else. The Arena ships no game art. */
export function GameCard({ card, price }: { card: CardModel; price?: boolean }) {
  const names = useNames();
  if (card.face_down) {
    return <div className="pcard down" role="img" aria-label="face-down card" />;
  }
  if (isPlayingCard(card)) {
    const enh = enhancement(card.key);
    const classes = [
      "pcard",
      isRed(card.suit) ? "red" : "",
      enh ? enh.toLowerCase() : "",
      card.debuff ? "debuff" : "",
      card.edition ? `edition-${card.edition}` : "",
    ].join(" ");
    const label = `${rankLabel(card.rank)}${suitGlyph(card.suit)}${enh ? ` (${enh})` : ""}${
      card.seal ? `, ${card.seal} seal` : ""
    }${card.edition ? `, ${card.edition}` : ""}${card.debuff ? ", debuffed" : ""}`;
    return (
      <div className={classes} role="img" aria-label={label} title={label}>
        <span className="corner">{rankLabel(card.rank)}</span>
        <span className="suit">{suitGlyph(card.suit)}</span>
        {card.seal && <span className={`mark seal-${card.seal}`} />}
      </div>
    );
  }
  const info = card.key ? names.info(card.key) : undefined;
  const name = info?.name ?? card.key ?? "?";
  const set = info?.set ?? "";
  const extras = [card.edition, card.eternal && "eternal", card.perishable && "perishable", card.rental && "rental"]
    .filter(Boolean)
    .join(", ");
  return (
    <div className={`item ${set}`} title={name}>
      <a className="name" href={wikiUrl(name)} target="_blank" rel="noreferrer">
        {name}
      </a>
      <span className="meta">
        {set}
        {extras && ` · ${extras}`}
        {price && card.cost != null && ` · $${card.cost}`}
      </span>
    </div>
  );
}

export function CardRow({ cards, price, empty }: { cards: CardModel[]; price?: boolean; empty?: string }) {
  if (!cards.length) return <p className="muted small">{empty ?? "None"}</p>;
  return (
    <div className="cards">
      {cards.map((c, i) => (
        <GameCard key={i} card={c} price={price} />
      ))}
    </div>
  );
}
