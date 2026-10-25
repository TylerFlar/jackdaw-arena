import { AnimatePresence, LayoutGroup, motion, MotionConfig } from "motion/react";
import type { CardModel } from "../../api/client";
import type { Popup, Scene, Slot, Zone } from "../../replay/scene";
import { num } from "../../lib/format";
import { GameCard } from "../PlayingCard";
import { BlindChoices, GameOver, RoundEval } from "./Screens";
import { Sidebar } from "./Sidebar";

/** The replay as Balatro lays it out: the run's numbers on the left; jokers and consumables
 * along the top; the play area, or the blind choice, shop, pack, round's end, in the middle;
 * the hand and the deck at the bottom. A card is the same element wherever it goes, so moving
 * it between areas animates it there. */
export function Board({ scene, animating, speed }: { scene: Scene; animating: boolean; speed: number }) {
  const f = scene.frame;
  const row = (zone: Zone, label: string, price = false) => (
    <Row zone={zone} label={label} slots={scene.zones[zone]} popups={scene.popups} price={price} />
  );
  const middle = (() => {
    switch (scene.phase) {
      case "blind_select":
        return <BlindChoices frame={f} />;
      case "shop":
        return (
          <div className="shop">
            {row("shop", "Shop")}
            <div className="shop-extras">
              {row("vouchers", "Vouchers", true)}
              {row("boosters", "Packs", true)}
              <span className="reroll">Reroll ${num(f.reroll_cost)}</span>
            </div>
          </div>
        );
      case "pack_opening":
        return (
          <div className="pack">
            {f.pack_info && (
              <span className="pack-title">
                {f.pack_info.kind} Pack · choose {f.pack_info.choices}
              </span>
            )}
            {row("pack", "Pack")}
          </div>
        );
      case "round_eval":
        return <RoundEval frame={f} />;
      case "game_over":
        return <GameOver frame={f} />;
      default:
        return row("play", "Played cards");
    }
  })();
  return (
    <MotionConfig transition={{ duration: animating ? 0.3 / speed : 0, ease: [0.2, 0.7, 0.3, 1] }} reducedMotion="user">
      <LayoutGroup>
        <div className={`game-board phase-${scene.phase}`}>
          <Sidebar scene={scene} />
          <div className="table">
            <div className="table-top">
              {row("jokers", `Jokers ${scene.zones.jokers.length}/${f.limits.jokers}`)}
              {row("consumables", `Consumables ${scene.zones.consumables.length}/${f.limits.consumables}`)}
            </div>
            <div className="table-middle">{middle}</div>
            <div className="table-bottom">
              {row("hand", `Hand ${scene.zones.hand.length}/${f.limits.hand}`)}
              <Deck count={f.deck_size} />
            </div>
          </div>
          <div className="banner-wrap" aria-live="polite">
            <AnimatePresence>
              {scene.banner && (
                <motion.div
                  key={scene.banner}
                  className="banner"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                >
                  {scene.banner}
                </motion.div>
              )}
              {scene.popups
                .filter((p) => p.card === null)
                .map((p) => (
                  <motion.div key={p.text} className={`popup big ${p.tone}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                    {p.text}
                  </motion.div>
                ))}
            </AnimatePresence>
          </div>
        </div>
      </LayoutGroup>
    </MotionConfig>
  );
}

function Row({ zone, label, slots, popups, price }: {
  zone: Zone; label: string; slots: Slot[]; popups: Popup[]; price: boolean;
}) { // prettier-ignore
  return (
    <div className={`zone-row zone-${zone}`} role="group" aria-label={label}>
      {slots.map((slot) => (
        <BoardCard
          key={slot.card.id}
          slot={slot}
          popups={popups.filter((p) => p.card === slot.card.id)}
          price={price || zone === "shop"}
        />
      ))}
    </div>
  );
}

/** A card: it comes in when it's new to the board, and otherwise moves from where it was. */
function BoardCard({ slot, popups, price }: { slot: Slot; popups: Popup[]; price: boolean }) {
  const { leaving } = slot;
  return (
    <motion.div
      layoutId={`card-${slot.card.id}`}
      className="board-card"
      data-card={slot.card.id}
      initial={slot.entering ? { opacity: 0, y: 28 } : false}
      animate={{
        opacity: leaving ? 0 : 1,
        y: slot.raised ? -16 : leaving === "discard" ? 28 : 0,
        scale: leaving === "shatter" ? 1.3 : slot.active ? 1.1 : 1,
        rotate: leaving === "shatter" ? 8 : 0,
      }}
    >
      <GameCard card={slot.card} price={price} />
      <div className="popups">
        <AnimatePresence>
          {popups.map((p, k) => (
            <motion.span
              key={`${k}${p.text}`}
              className={`popup ${p.tone}`}
              initial={{ opacity: 0, y: 8, scale: 0.7 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8 }}
            >
              {p.text}
            </motion.span>
          ))}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

const BACK: CardModel = {
  face_down: true, key: null, front: null, suit: null, rank: null, edition: null, seal: null,
  debuff: false, cost: null, sell_cost: null, eternal: false, perishable: false, rental: false,
}; // prettier-ignore

function Deck({ count }: { count: number }) {
  return (
    <div className="deck-pile" role="img" aria-label={`${count} cards in the deck`}>
      <GameCard card={BACK} />
      <span className="deck-count">{count}</span>
    </div>
  );
}
