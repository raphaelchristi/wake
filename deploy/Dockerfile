# Wake — production multistage image.
#
# Stage 1 builds a wheel; stage 2 installs into a slim image and runs
# either ``wake server`` (API tier) or ``wake worker`` (harness tier).
#
# Differences from the dev Dockerfile at repo root:
#   - includes Postgres + Infisical + LiteLLM optional deps preinstalled
#   - pinned non-root user, read-only rootfs friendly
#   - cooperates with the multi-worker advisory-lock topology

FROM python:3.11-slim AS builder

WORKDIR /build

RUN python -m pip install --no-cache-dir --upgrade pip build

# Bring the workspace into the builder so editable adapter installs work.
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY adapters/ ./adapters/

RUN python -m build --wheel --outdir /build/dist


FROM python:3.11-slim

LABEL org.opencontainers.image.title="wake"
LABEL org.opencontainers.image.description="Wake — production substrate (API + worker)."
LABEL org.opencontainers.image.source="https://github.com/raphaelchristi/wake"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WAKE_HOME=/data/wake

WORKDIR /app

# Core wheel + Phase 4 adapters preinstalled so the same image serves
# api / worker / dev profiles. Production deployments may slim this
# image further by removing adapters they don't need.
COPY --from=builder /build/dist/*.whl /tmp/
COPY --from=builder /build/adapters /tmp/adapters
RUN pip install --no-cache-dir /tmp/*.whl \
    && pip install --no-cache-dir \
        /tmp/adapters/vault-infisical \
        /tmp/adapters/llm-litellm \
    && rm -rf /tmp/*.whl /tmp/adapters

RUN useradd --create-home --uid 10001 wake \
    && mkdir -p /data/wake \
    && chown -R wake:wake /data
USER wake

EXPOSE 8080

# Default to API tier. The compose stack overrides CMD on the worker
# service.
ENTRYPOINT ["wake"]
CMD ["server", "--host", "0.0.0.0", "--port", "8080"]
