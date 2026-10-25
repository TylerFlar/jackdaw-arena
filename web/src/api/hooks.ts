import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "./client";

export function useVersion() {
  return useQuery({
    queryKey: ["version"],
    queryFn: () => unwrap(api.GET("/api/version")),
    staleTime: Infinity,
  });
}

export function useTracks() {
  return useQuery({
    queryKey: ["tracks"],
    queryFn: () => unwrap(api.GET("/api/tracks")),
    staleTime: 5 * 60_000,
  });
}

export function useLeaderboard(track: string) {
  return useQuery({
    queryKey: ["leaderboard", track],
    queryFn: () => unwrap(api.GET("/api/leaderboard", { params: { query: { track } } })),
    // Keep the last board on screen while another track loads: no flash, no layout jump.
    placeholderData: (previous) => previous,
  });
}

export function useAgent(slug: string, mine = false) {
  return useQuery({
    queryKey: ["agent", slug, mine],
    queryFn: () =>
      unwrap(
        mine
          ? api.GET("/api/me/agents/{slug}", { params: { path: { slug } } })
          : api.GET("/api/agents/{slug}", { params: { path: { slug } } }),
      ),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
}

export function useAgentEpisodes(slug: string, mine = false) {
  return useInfiniteQuery({
    queryKey: ["agent-episodes", slug, mine],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => {
      const query = { limit: 20, ...(pageParam ? { before: pageParam } : {}) };
      return unwrap(
        mine
          ? api.GET("/api/me/agents/{slug}/episodes", { params: { path: { slug }, query } })
          : api.GET("/api/agents/{slug}/episodes", { params: { path: { slug }, query } }),
      );
    },
    getNextPageParam: (last) => last.next ?? undefined,
  });
}

export function useEpisode(id: string, mine = false) {
  return useQuery({
    queryKey: ["episode", id, mine],
    queryFn: () => {
      const params = { path: { episode_id: id } };
      return unwrap(
        mine ? api.GET("/api/me/episodes/{episode_id}", { params }) : api.GET("/api/episodes/{episode_id}", { params }),
      );
    },
    // A running episode changes; an ended one never does.
    refetchInterval: (q) => (q.state.data?.status === "running" ? 5000 : false),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
}

export const FRAME_PAGE = 200;

export function useFrames(id: string, page: number, enabled: boolean, mine = false) {
  return useQuery({
    queryKey: ["frames", id, page, mine],
    enabled,
    staleTime: Infinity,
    queryFn: () => {
      const params = { path: { episode_id: id }, query: { from: page * FRAME_PAGE, limit: FRAME_PAGE } };
      return unwrap(
        mine
          ? api.GET("/api/me/episodes/{episode_id}/frames", { params })
          : api.GET("/api/episodes/{episode_id}/frames", { params }),
      );
    },
  });
}

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: () => unwrap(api.GET("/auth/providers")),
    staleTime: Infinity,
  });
}

/** The signed-in user's account, or null. Asks /auth/session first (always 200), so a
 * signed-out visit doesn't log a 401 on every page. */
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const { user } = await unwrap(api.GET("/auth/session"));
      if (!user) return null;
      try {
        return await unwrap(api.GET("/api/me"));
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 30_000,
  });
}

function useInvalidateMe() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["me"] });
}

export function useCreateAgent() {
  const done = useInvalidateMe();
  return useMutation({
    mutationFn: (body: { slug: string; name: string; description?: string; url?: string | null; unlisted?: boolean }) =>
      unwrap(api.POST("/api/me/agents", { body })),
    onSuccess: done,
  });
}

export function useUpdateAgent() {
  const done = useInvalidateMe();
  return useMutation({
    mutationFn: ({ slug, ...body }: { slug: string; unlisted?: boolean; name?: string; description?: string }) =>
      unwrap(api.PATCH("/api/me/agents/{slug}", { params: { path: { slug } }, body })),
    onSuccess: done,
  });
}

export function useCreateToken() {
  const done = useInvalidateMe();
  return useMutation({
    mutationFn: ({ slug, label }: { slug: string; label: string }) =>
      unwrap(api.POST("/api/me/agents/{slug}/tokens", { params: { path: { slug } }, body: { label } })),
    onSuccess: done,
  });
}

export function useRevokeToken() {
  const done = useInvalidateMe();
  return useMutation({
    mutationFn: async (tokenId: string) => {
      const { response } = await api.DELETE("/api/me/tokens/{token_id}", {
        params: { path: { token_id: tokenId } },
      });
      if (!response.ok) throw new ApiError(response.status, "error", "couldn't revoke the token");
    },
    onSuccess: done,
  });
}

export function useSignOut() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.POST("/auth/logout");
    },
    onSuccess: () => qc.setQueryData(["me"], null),
  });
}
