import type { CSSProperties } from "react";
import { ART_ROOT, type Art } from "./art";
import type { Cell } from "./cells";

/** One atlas cell, filling the element: CSS sets the size, so any size scales the sprite. */
export function Sprite({ art, cell, className }: { art: Art; cell: Cell; className?: string }) {
  return <span aria-hidden="true" className={className ? `sprite ${className}` : "sprite"} style={spriteStyle(art, cell)} />;
}

export function spriteStyle(art: Art, cell: Cell): CSSProperties {
  const a = art.atlases[cell.atlas];
  const cols = a.size[0] / a.cell[0];
  const rows = a.size[1] / a.cell[1];
  const at = (i: number, n: number) => (n > 1 ? (i / (n - 1)) * 100 : 0);
  return {
    backgroundImage: `url(${ART_ROOT}${a.file})`,
    backgroundSize: `${cols * 100}% ${rows * 100}%`,
    backgroundPosition: `${at(cell.x, cols)}% ${at(cell.y, rows)}%`,
  };
}
