# syntax=docker/dockerfile:1.7
# The Arena API: one image for local Docker and AWS Lambda.
#
# On Lambda, the Lambda Web Adapter extension (copied into /opt/extensions) starts uvicorn, waits
# for /healthz, and turns invocations into HTTP requests. Function URL requests stay HTTP;
# scheduler and direct invocations become POST /events. Outside Lambda the extension never
# starts and the same CMD serves directly.
#
#   docker build -t arena-api api/
#   docker run -p 8000:8000 -e ARENA_DATABASE_URL=... arena-api

FROM public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 AS adapter
FROM ghcr.io/astral-sh/uv:0.12.19 AS uv

FROM public.ecr.aws/docker/library/python:3.13-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
# Dependencies first (a cached layer). --no-build: every dependency must come as a wheel, so a
# missing one fails here instead of compiling (jackdaw comes from its release's manylinux wheel).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra aws --no-install-project --no-build
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra aws --no-editable

FROM public.ecr.aws/docker/library/python:3.13-slim-trixie
RUN useradd --create-home --uid 10001 arena
COPY --from=adapter /lambda-adapter /opt/extensions/lambda-adapter
COPY --from=build /app/.venv /app/.venv
# The git SHA this image was built from (deploys pass it); served by /api/version.
ARG BUILD=dev
ENV ARENA_BUILD=$BUILD \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    AWS_LWA_PORT=8000 \
    AWS_LWA_READINESS_CHECK_PATH=/healthz \
    AWS_LWA_PASS_THROUGH_PATH=/events
USER arena
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "arena.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
