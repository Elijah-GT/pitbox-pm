# Pit Box, built for Fly.io (or any container host).
#
# Two stages: Node builds the React UI, then a slim Python image runs the API and
# serves that build. Node does not ship in the final image -- it is a build tool,
# not a runtime dependency, and leaving it out keeps the image small and the
# attack surface boring.
#
# Build and run locally exactly as Fly will:
#   docker build -t pitbox .
#   docker run --rm -p 8000:8000 -e PITBOX_AUTH_MODE=none -e PITBOX_HOST=0.0.0.0 pitbox

# --- stage 1: the React build -------------------------------------------------
FROM node:22-slim AS ui

WORKDIR /ui

# Copy the manifests alone first. Docker caches this layer, so `npm ci` only
# re-runs when a dependency actually changed -- not on every source edit.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- stage 2: the runtime -----------------------------------------------------
FROM python:3.13-slim AS runtime

# PYTHONUNBUFFERED so logs reach `fly logs` immediately rather than sitting in a
# buffer until the process exits -- which is exactly when you need them most.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# cloudflared, so the container can dial out to Cloudflare itself and the app
# never needs a public port. Started by the entrypoint only when TUNNEL_TOKEN is
# set; see deploy/fly-entrypoint.sh and docs/FLY.md.
#
# Pin CLOUDFLARED_VERSION to a release tag if you would rather not track latest.
ARG CLOUDFLARED_VERSION=latest
ARG TARGETARCH=amd64
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && if [ "$CLOUDFLARED_VERSION" = "latest" ]; then \
         CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH}"; \
       else \
         CF_URL="https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${TARGETARCH}"; \
       fi \
    && curl -fsSL "$CF_URL" -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared \
    && cloudflared --version \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Dependencies before source, again for the layer cache.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/
COPY scripts/ ./scripts/
COPY deploy/fly-entrypoint.sh ./deploy/fly-entrypoint.sh
COPY --from=ui /ui/dist ./frontend/dist

RUN chmod +x ./deploy/fly-entrypoint.sh

# The volume mounts over this at runtime. Creating it here means the image also
# runs without a volume, which is what `docker run` above does.
RUN mkdir -p /data/storage

# Defaults for the recommended deployment: identity verified against Cloudflare's
# signature, database and uploads on the mounted volume, and the app listening on
# loopback only because cloudflared is in the same container. fly.toml overrides
# PITBOX_HOST if you choose to expose a public port instead.
ENV PITBOX_AUTH_MODE=cloudflare \
    PITBOX_DATABASE_URL=sqlite:////data/pitbox.db \
    PITBOX_STORAGE_DIR=/data/storage \
    PITBOX_COOKIE_SECURE=true \
    PITBOX_HOST=127.0.0.1 \
    PITBOX_PORT=8000

EXPOSE 8000

ENTRYPOINT ["./deploy/fly-entrypoint.sh"]
