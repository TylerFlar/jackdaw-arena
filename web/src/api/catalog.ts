import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api, unwrap } from "./client";

type Entry = { name: string; set?: string | null; rarity?: number | null; boss?: boolean | null };

/** Display names for the game's keys (jokers, tarots, blinds, tags...), from /api/catalog. */
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
    return { info, name: (key: string) => info(key)?.name ?? key, ready: Boolean(data) };
  }, [data]);
}
