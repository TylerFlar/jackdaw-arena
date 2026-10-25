import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Leaderboard = Schemas["Leaderboard"];
export type BoardRow = Schemas["BoardRow"];
export type Stats = Schemas["Stats"];
export type AgentPage = Schemas["AgentPage"];
export type EpisodeSummary = Schemas["EpisodeSummary"];
export type EpisodePage = Schemas["EpisodePage"];
export type Frame = Schemas["Frame"];
export type FramesDoc = Schemas["FramesDoc"];
export type CardModel = Schemas["CardModel"];
export type MeDoc = Schemas["MeDoc"];
export type MyAgent = Schemas["MyAgent"];
export type NewToken = Schemas["NewToken"];
export type TrackInfo = Schemas["TrackInfo"];
export type Final = Schemas["Final"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** Every cookie-authenticated change carries this header: a cross-site page can't send it
 * without a CORS preflight the API never answers. */
const csrf: Middleware = {
  onRequest({ request }) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      request.headers.set("X-Arena-CSRF", "1");
    }
    return request;
  },
};

export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  // Look fetch up per call rather than once at import, so anything that wraps it later (test
  // mocks, monitoring) sees every request.
  fetch: (request: Request) => globalThis.fetch(request),
});
api.use(csrf);

type Result<T> = { data?: T; error?: unknown; response: Response };

/** The data of a response, or an ApiError carrying the server's error code and message. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok || data === undefined) {
    const body = (error ?? {}) as { error?: string; message?: string };
    throw new ApiError(response.status, body.error ?? "error", body.message ?? response.statusText);
  }
  return data;
}
