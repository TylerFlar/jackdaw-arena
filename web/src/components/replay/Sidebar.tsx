import { motion } from "motion/react";
import { useNames } from "../../api/catalog";
import { Icon } from "../../art/Icon";
import type { Num, Scene } from "../../replay/scene";
import { num } from "../../lib/format";

const TITLES: Record<string, string> = {
  blind_select: "Choose your next blind",
  shop: "Shop",
  pack_opening: "Pack",
  round_eval: "Round won",
  game_over: "Game over",
};

/** A number that pops when it changes. */
function Pop({ value, className }: { value: Num; className?: string }) {
  return (
    <motion.span key={String(value)} className={className} initial={{ scale: 1.25 }} animate={{ scale: 1 }}>
      {num(value)}
    </motion.span>
  );
}

/** The run's numbers, as Balatro's left column shows them. */
export function Sidebar({ scene }: { scene: Scene }) {
  const names = useNames();
  const { hud, frame: f } = scene;
  const blind = f.blind?.key ? f.blind : null;
  return (
    <aside className="hud" aria-label="Run">
      <div className="hud-box hud-blind">
        {blind ? (
          <>
            <Icon atlas="blinds" entry={names.info(blind.key)} />
            <div>
              <strong>{blind.name}</strong>
              <span>
                Score at least <b className="target">{num(blind.chips)}</b>
              </span>
              <span className="reward">Reward {"$".repeat(Math.min(Number(blind.dollars) || 0, 8))}</span>
            </div>
          </>
        ) : (
          <strong>{TITLES[scene.phase] ?? "Blind"}</strong>
        )}
      </div>
      <div className="hud-box hud-score">
        <span className="k">Round score</span>
        <Pop value={hud.score} className="score-n" />
      </div>
      <div className="hud-box hud-hand">
        <span className="hand-name">
          {hud.hand ? hud.hand.name : " "}
          {hud.hand && <small> lvl.{num(hud.hand.level)}</small>}
        </span>
        <span className="chips-mult">
          <Pop value={hud.hand?.chips ?? 0} className="chips" />
          <span className="times">X</span>
          <Pop value={hud.hand?.mult ?? 0} className="mult" />
        </span>
      </div>
      <div className="hud-pair">
        <div className="hud-box">
          <span className="k">Hands</span>
          <Pop value={hud.hands} className="hands" />
        </div>
        <div className="hud-box">
          <span className="k">Discards</span>
          <Pop value={hud.discards} className="discards" />
        </div>
      </div>
      <div className="hud-box hud-money">
        <Pop value={`$${hud.dollars}`} className="money" />
      </div>
      <div className="hud-pair">
        <div className="hud-box">
          <span className="k">Ante</span>
          <b>{hud.ante}/8</b>
        </div>
        <div className="hud-box">
          <span className="k">Round</span>
          <b>{hud.round}</b>
        </div>
      </div>
      {f.tags.length > 0 && (
        <div className="hud-tags" aria-label="Tags">
          {f.tags.map((t, k) => (
            <span key={k} title={t.name}>
              <Icon atlas="tags" entry={names.info(t.key)} />
            </span>
          ))}
        </div>
      )}
    </aside>
  );
}
