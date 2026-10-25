import type { Frame } from "../../api/client";
import { num } from "../../lib/format";
import { CardRow } from "../PlayingCard";

const PHASES: Record<string, string> = {
  blind_select: "Choosing a blind",
  selecting_hand: "Playing the blind",
  round_eval: "Round won",
  shop: "Shop",
  pack_opening: "Opening a pack",
  game_over: "Game over",
};

export function StatePanel({ frame }: { frame: Frame }) {
  const f = frame;
  return (
    <div>
      <div className="statline">
        <Stat k="Phase" v={PHASES[f.phase] ?? f.phase} />
        <Stat k="Ante" v={f.ante} />
        <Stat k="Round" v={f.round} />
        <Stat k="Money" v={`$${f.dollars}`} />
        <Stat k="Hands" v={f.hands_left} />
        <Stat k="Discards" v={f.discards_left} />
        <Stat k="Deck" v={f.deck_size} />
      </div>

      {f.blind && f.phase !== "blind_select" && (
        <div className="zone">
          <h3>Blind</h3>
          <div className="row">
            <strong>{f.blind.name}</strong>
            {f.blind.boss && <span className="badge">boss</span>}
            {f.blind.disabled && <span className="badge">disabled</span>}
            <span className="muted">
              score {num(f.chips)} / {num(f.blind.chips)}
            </span>
          </div>
        </div>
      )}

      {f.phase === "blind_select" && f.blinds && (
        <div className="zone">
          <h3>Blinds</h3>
          <div className="blinds">
            {(["small", "big", "boss"] as const).map((slot) => {
              const b = f.blinds?.[slot];
              if (!b) return null;
              return (
                <div key={slot} className={`blind ${b.status ?? ""}`}>
                  <strong>{b.name}</strong>
                  <div className="muted small">
                    {num(b.score)} chips{b.tag && ` · skip: ${b.tag}`}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {f.last_score && (f.phase === "selecting_hand" || f.phase === "round_eval") && (
        <div className="zone">
          <h3>Last hand</h3>
          <div className="row">
            <span>{f.last_score.hand_type}</span>
            {f.last_score.debuffed ? (
              <span className="badge bad">debuffed by the boss</span>
            ) : (
              <span className="score" aria-label={`${num(f.last_score.chips)} chips times ${num(f.last_score.mult)} mult`}>
                <span className="chips">{num(f.last_score.chips)}</span>×
                <span className="mult">{num(f.last_score.mult)}</span>= {num(f.last_score.total)}
              </span>
            )}
          </div>
        </div>
      )}

      <div className="zone">
        <h3>Jokers</h3>
        <CardRow cards={f.jokers} empty="No jokers" />
      </div>
      {f.consumables.length > 0 && (
        <div className="zone">
          <h3>Consumables</h3>
          <CardRow cards={f.consumables} />
        </div>
      )}
      {(f.phase === "selecting_hand" || f.hand.length > 0) && (
        <div className="zone">
          <h3>Hand</h3>
          <CardRow cards={f.hand} empty="Empty hand" />
        </div>
      )}
      {f.phase === "shop" && (
        <div className="zone">
          <h3>Shop</h3>
          <CardRow cards={[...f.shop.cards, ...f.shop.vouchers, ...f.shop.boosters]} price empty="Sold out" />
        </div>
      )}
      {f.phase === "pack_opening" && (
        <div className="zone">
          <h3>Pack</h3>
          <CardRow cards={f.pack} />
        </div>
      )}
      {f.tags.length > 0 && (
        <div className="zone">
          <h3>Tags</h3>
          <div className="row">
            {f.tags.map((t, i) => (
              <span key={i} className="badge">
                {t.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ k, v }: { k: string; v: string | number }) {
  return (
    <div>
      <span className="k">{k}</span>
      <span className="v">{v}</span>
    </div>
  );
}
