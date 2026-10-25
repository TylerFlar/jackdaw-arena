"""The application factory. ``uvicorn --factory arena.main:create_app`` serves it, locally and
on Lambda (behind the Lambda Web Adapter)."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from arena import __version__
from arena.auth.oauth import SignIn
from arena.clock import Clock, utcnow
from arena.db.engine import make_engine
from arena.engine.live import EnvFactory, gym_env
from arena.routes import account, agent_api, auth, events, health, public
from arena.services.episodes import EpisodeService, Limits, ProtocolError
from arena.services.seeds import SeedSource, secure_seeds
from arena.settings import Settings, load_settings

# Paths CloudFront never forwards: Lambda pass-through events arrive here from the adapter
# inside the execution environment, not over the network.
_INTERNAL = ("/events",)


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    clock: Clock = utcnow,
    seeds: SeedSource = secure_seeds,
    env_factory: EnvFactory = gym_env,
    http: httpx.Client | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    engine = engine or make_engine(settings)
    http = http or httpx.Client(follow_redirects=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        http.close()
        engine.dispose()

    app = FastAPI(
        title="Jackdaw Arena",
        version=__version__,
        description="Hosted, verifiable evaluation for Balatro agents on the jackdaw engine.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.clock = clock
    app.state.signin = SignIn(settings, http)
    app.state.episodes = EpisodeService(
        engine,
        clock,
        seeds,
        env_factory,
        cache_size=settings.cache_size,
        limits=Limits(
            max_running=settings.max_running_per_agent,
            max_batch=settings.max_batch,
            max_new=settings.max_new_episodes,
        ),
    )

    # CloudFront doesn't compress what it doesn't cache (agent steps, account pages), so the
    # app does: a step response shrinks about 7x. Added first, so it sits inside the middlewares
    # below and sees each response whole (they stream, which would defeat minimum_size).
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

    secret = (
        settings.origin_verify_secret.get_secret_value().encode()
        if (settings.origin_verify_secret)
        else None
    )

    @app.middleware("http")
    async def origin_verify(request: Request, call_next):  # type: ignore[no-untyped-def]
        # In production every request must come through CloudFront, which adds the secret
        # header. A request without it reached the Function URL directly.
        if secret is not None and not request.url.path.startswith(_INTERNAL):
            given = request.headers.get("x-origin-verify", "").encode()
            if not hmac.compare_digest(given, secret):
                return JSONResponse({"error": "forbidden", "message": "forbidden"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ProtocolError)
    async def protocol_error(_: Request, exc: ProtocolError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(
            exc.status_code, "error"
        )
        return JSONResponse(
            {"error": code, "message": str(exc.detail)},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"error": "bad_request", "message": "invalid request", "detail": exc.errors()},
            status_code=422,
        )

    @app.middleware("http")
    async def no_store(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        # Agent and account traffic is per-caller: never cache it anywhere.
        if request.url.path.startswith(("/api/v1", "/api/me", "/api/admin", "/auth")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(health.router)
    app.include_router(agent_api.router)
    app.include_router(public.router)
    app.include_router(account.router)
    app.include_router(account.admin)
    app.include_router(auth.router)
    app.include_router(events.router)
    return app
