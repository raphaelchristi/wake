# Wake server — multistage build.
#
# Stage 1 builds a wheel; stage 2 installs it into a clean slim image
# and runs `wake server`. The entrypoint is `wake`, so by default the
# container starts the API server on :8080.

FROM python:3.11-slim AS builder

WORKDIR /build

# Keep the build layer cacheable: install build tooling, then copy
# source. (We don't need full system deps because hatchling is pure
# Python.)
RUN python -m pip install --no-cache-dir --upgrade pip build

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN python -m build --wheel --outdir /build/dist


FROM python:3.11-slim

LABEL org.opencontainers.image.title="wake"
LABEL org.opencontainers.image.description="Wake — durable runtime substrate for AI agents."
LABEL org.opencontainers.image.source="https://github.com/raphaelchristi/wake"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WAKE_HOME=/data/wake

WORKDIR /app

# Install the wheel built in stage 1. We pull in the *runtime* deps
# (FastAPI, uvicorn, etc.) only — dev deps stay in the builder.
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Non-root user for the running container. The data dir gets owned by
# this user so SQLite + workspaces work without root.
RUN useradd --create-home --uid 10001 wake \
    && mkdir -p /data/wake \
    && chown -R wake:wake /data
USER wake

EXPOSE 8080

ENTRYPOINT ["wake"]
CMD ["server", "--host", "0.0.0.0", "--port", "8080"]
