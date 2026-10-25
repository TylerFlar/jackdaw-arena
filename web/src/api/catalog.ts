import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api, unwrap, type Schemas } from "./client";

export type Entry = Schemas["CatalogEntry"];
type Table = "centers" | "blinds" | "tags" | "stakes";

/** Names and sprite cells for the game's keys (jokers, tarots, blinds, tags, stakes...), from
 * /api/catalog. */
export function useNames() {
  const { data } = useQuery({
    queryKey: ["catalog"],
    queryFn: () => unwrap(api.GET("/api/catalog")),
    staleTime: Infinity,
  });
  return useMemo(() => {
    const tables = data ? [data.centers, data.blinds, data.tags] : [];
    const info = (key: string): Entry | undefined => {
      for (const t of tables) if (t[key]) return t[key];
      return undefined;
    };
    /** The entry named ``name`` in a table: the blind-select row only has names. */
    const named = (table: Table, name: string | null | undefined): Entry | undefined => {
      const t = data?.[table];
      return t && name ? Object.values(t).find((e) => e.name === name) : undefined;
    };
    const stake = (level: number): Entry | undefined => data?.stakes?.[String(level)];
    return { info, named, stake, name: (key: string) => info(key)?.name ?? key, ready: Boolean(data) };
  }, [data]);
}
