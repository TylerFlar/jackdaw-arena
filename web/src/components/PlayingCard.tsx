import type { CardModel } from "../api/client";
import { useNames } from "../api/catalog";
import { useArt, useDeckBack, type Art } from "../art/art";
import { cardArt, type CardArt } from "../art/cells";
import { Sprite } from "../art/Sprite";
import { num } from "../lib/format";
import { enhancement, isPlayingCard, isRed, rankLabel, suitGlyph, wikiUrl } from "../lib/cards";

/** A card: Balatro's sprites when the site has them, else a playing card in CSS (rank, suit
 * glyph, enhancement, seal, edition) or a named tile for anything else. */
export function GameCard({ card, price }: { card: CardModel; price?: boolean }) {
  const names = useNames();
  const art = useArt();
  const back = useDeckBack();
  const name = card.key ? names.name(card.key) : "?";
  if (art === undefined || (art && !names.ready)) {
    // An empty slot until it's known how to draw the card: no flash of the plain one.
    return <span className="gcard pending" role="img" aria-label={describe(card, name)} />;
  }
  const drawn = art ? cardArt(card, names.info, back) : null;
  if (art && drawn) {
    return <ArtCard art={art} drawn={drawn} card={card} name={name} price={price} />;
  }
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
    const label = describe(card, name);
    return (
      <div className={classes} role="img" aria-label={label} title={label}>
        <span className="corner">{rankLabel(card.rank)}</span>
        <span className="suit">{suitGlyph(card.suit)}</span>
        {card.seal && <span className={`mark seal-${card.seal}`} />}
      </div>
    );
  }
  const set = (card.key && names.info(card.key)?.set) ?? "";
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

/** "A♥ (Glass), Gold seal", or "Joker, foil, eternal". */
export function describe(card: CardModel, name: string): string {
  if (card.face_down) return "face-down card";
  const enh = enhancement(card.key);
  const head = isPlayingCard(card) ? `${rankLabel(card.rank)}${suitGlyph(card.suit)}${enh ? ` (${enh})` : ""}` : name;
  const extras = [
    card.seal && `${card.seal} seal`,
    card.edition,
    card.eternal && "eternal",
    card.perishable && "perishable",
    card.rental && "rental",
    card.debuff && "debuffed",
  ].filter(Boolean);
  return [head, ...extras].join(", ");
}

function ArtCard({ art, drawn, card, name, price }: {
  art: Art; drawn: CardArt; card: CardModel; name: string; price?: boolean;
}) { // prettier-ignore
  const label = describe(card, name);
  const classes = ["gcard", card.edition ? `ed-${card.edition}` : "", drawn.scale ? "wee" : ""].filter(Boolean);
  const face = (
    <span className={classes.join(" ")} role="img" aria-label={label} title={label}>
      {drawn.layers.map((cell, i) => (
        <Sprite key={i} art={art} cell={cell} />
      ))}
      {drawn.soul && <Sprite art={art} cell={drawn.soul} className="soul" />}
    </span>
  );
  const linked = !card.face_down && !isPlayingCard(card);
  return (
    <span className="gslot">
      {linked ? (
        <a href={wikiUrl(name)} target="_blank" rel="noreferrer">
          {face}
        </a>
      ) : (
        face
      )}
      {price && card.cost != null && <span className="price">${num(card.cost)}</span>}
    </span>
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
