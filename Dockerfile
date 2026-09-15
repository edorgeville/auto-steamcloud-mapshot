# syntax=docker/dockerfile:1
#
# This image ships no Factorio game files. The client is downloaded at runtime
# with the operator's own factorio.com credentials.
#
# amd64 only: no arm64 Linux Factorio client exists.

# Bump these two together; the checksum is printed on the mapshot release page.
ARG MAPSHOT_VERSION=0.0.28
ARG MAPSHOT_SHA256=e2f2d72c20272f1519f736e2f5b8d84a9241894e12a9310bf06a5fc1a0828825
ARG SCSD_VERSION=0.0.84
ARG CRONSIM_VERSION=2.7


FROM debian:trixie-slim AS mapshot
ARG MAPSHOT_VERSION
ARG MAPSHOT_SHA256
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -fsSL -o /mapshot \
      "https://github.com/Palats/mapshot/releases/download/${MAPSHOT_VERSION}/mapshot-linux" \
    && echo "${MAPSHOT_SHA256}  /mapshot" | sha256sum -c - \
    && chmod +x /mapshot


FROM debian:trixie-slim AS venv
ARG SCSD_VERSION
ARG CRONSIM_VERSION
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir "scsd==${SCSD_VERSION}" "cronsim==${CRONSIM_VERSION}"


FROM debian:trixie-slim
ARG MAPSHOT_VERSION

LABEL org.opencontainers.image.title="factorio-mapshot-cloud" \
      org.opencontainers.image.description="Renders a Steam Cloud Factorio save with mapshot and serves it. Ships no game files." \
      org.opencontainers.image.licenses="MIT"

# xauth is required by xvfb-run and is only a recommends of xvfb.
# The mesa packages provide the llvmpipe software rasteriser; Factorio has no
# headless rendering path, so a real GL context is mandatory.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        gosu \
        libasound2t64 \
        libegl1 \
        libgl1 \
        libgl1-mesa-dri \
        libglx-mesa0 \
        libpulse0 \
        libx11-6 \
        libxcursor1 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxinerama1 \
        libxrandr2 \
        libxrender1 \
        python3 \
        tini \
        xauth \
        xvfb \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=mapshot /mapshot /usr/local/bin/mapshot
COPY --from=venv /opt/venv /opt/venv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    MAPSHOT_VERSION=${MAPSHOT_VERSION} \
    FACTORIO_BUILD=expansion \
    FACTORIO_VERSION=auto \
    RENDER_INTERVAL=3600 \
    SERVE_PORT=8080 \
    MAPSHOT_AREA=player \
    MAPSHOT_SURFACE=_all_ \
    PUID=1000 \
    PGID=1000

WORKDIR /app
COPY app /app/app
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /config /data /output

VOLUME ["/config", "/data", "/output"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["/opt/venv/bin/python", "-m", "app", "healthcheck"]

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/entrypoint.sh"]
CMD []
