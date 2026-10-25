import type { Entry } from "../api/catalog";
import { useArt } from "./art";
import { tableCell, type IconAtlas } from "./cells";
import { Sprite } from "./Sprite";

/** A blind's chip, a tag, a stake's chip or a deck when the site has the art; nothing
 * otherwise. */
export function Icon({ atlas, entry }: { atlas: IconAtlas; entry: Entry | undefined }) {
  const art = useArt();
  const cell = art ? tableCell(atlas, entry?.pos) : null;
  return art && cell ? <Sprite art={art} cell={cell} className={`icon ${atlas}`} /> : null;
}
