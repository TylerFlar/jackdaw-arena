import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";

/** Balatro's sprites and font, when the site has them: they're LocalThunk's, so they're never
 * in the repository (infra/scripts/extract_art.py, upload_art.py). Without them, the site draws
 * plain cards. */
export const ART_ROOT = "/art/v1/";

export type AtlasName =
  | "cards"
  | "centers"
  | "jokers"
  | "tarots"
  | "vouchers"
  | "boosters"
  | "stickers"
  | "tags"
  | "stakes"
  | "blinds";

export type Atlas = { file: string; cell: [number, number]; size: [number, number] };
export type Art = { version: number; atlases: Record<AtlasName, Atlas>; font: string; credit: string };

function isArt(x: unknown): x is Art {
  const a = x as Art | null;
  return Boolean(a && typeof a === "object" && a.atlases?.cards && a.atlases.jokers && typeof a.credit === "string");
}

async function loadArt(): Promise<Art | null> {
  try {
    const r = await fetch(`${ART_ROOT}manifest.json`);
    if (!r.ok) return null;
    const art: unknown = await r.json();
    if (!isArt(art)) return null;
    loadFont(art.font);
    return art;
  } catch {
    return null; // missing (a 403 from the bucket, or HTML), or the network
  }
}

/** The pixel font for headings and numbers: the page switches to it once it has loaded. */
function loadFont(file: string): void {
  if (typeof FontFace === "undefined" || !document.fonts) return;
  const face = new FontFace("m6x11", `url(${ART_ROOT}${file})`);
  face
    .load()
    .then((loaded) => {
      document.fonts.add(loaded);
      document.documentElement.dataset.font = "game";
    })
    .catch(() => undefined);
}

/** The art manifest; null when the site has none, undefined until that's known. */
export function useArt(): Art | null | undefined {
  const { data, isPending } = useQuery({
    queryKey: ["art"],
    queryFn: loadArt,
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  });
  return isPending ? undefined : (data ?? null);
}

/** The deck whose back face-down cards show. */
export const DeckBack = createContext("b_red");
export const useDeckBack = () => useContext(DeckBack);
