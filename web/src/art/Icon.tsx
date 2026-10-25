import type { Entry } from "../api/catalog";
import { useArt } from "./art";
import { tableCell } from "./cells";
import { Sprite } from "./Sprite";

/** A blind's chip, a tag or a stake's chip when the site has the art; nothing otherwise. */
export function Icon({ atlas, entry }: { atlas: "blinds" | "tags" | "stakes"; entry: Entry | undefined }) {
  const art = useArt();
  const cell = art ? tableCell(atlas, entry?.pos) : null;
  return art && cell ? <Sprite art={art} cell={cell} className={`icon ${atlas}`} /> : null;
}
