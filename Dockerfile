# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
#
# The Genesis Mesh image: a Network Authority (SERVICE_ROLE=na, the default)
# or a mesh node (SERVICE_ROLE=node), installed from a wheel built from this
# checkout. No source tree and no key material enter the runtime image; keys
# are mounted, handed over as secret files, or read from Key Vault.
#
#   docker build -t genesis-mesh .
#
# Dependencies come from hash-pinned locks (requirements-image.lock for the
# runtime, requirements-build.lock for the wheel build); regenerate them with
# scripts/lock_image_requirements.py when pyproject.toml changes.

ARG PYTHON_IMAGE=python:3.14-alpine@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72

# The wheel is pure Python: build it natively, then install it per target platform.
FROM --platform=$BUILDPLATFORM ${PYTHON_IMAGE} AS build
WORKDIR /src
COPY requirements-build.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements-build.lock
COPY . .
RUN python -m build --wheel --no-isolation --outdir /dist

FROM ${PYTHON_IMAGE}
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="genesis-mesh" \
      org.opencontainers.image.description="Genesis Mesh Network Authority and mesh node" \
      org.opencontainers.image.source="https://github.com/GenesisMeshLabs/genesismesh" \
      org.opencontainers.image.documentation="https://docs.genesismesh.org/operations/container-images.html" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/genesis_mesh_na.db

# Alpine: its packages carry no high-severity findings, where Debian's carried
# unfixed ones the Network Authority never uses. Security fixes newer than the
# pinned base are applied at build time; tini runs as PID 1 so SIGTERM reaches
# the server or node; bash runs start.sh and the health check. The PostgreSQL
# driver is included for HA mode (v0.60). pip and the bundled ensurepip wheels
# are removed afterwards: the runtime never installs packages, and their
# vendored copies only add scanner findings. /data is owned by uid 10001 and
# group 0 (mode 2770), so a platform that assigns another uid in group 0
# (OpenShift) can still write it.
COPY requirements-image.lock /tmp/requirements-image.lock
RUN --mount=type=bind,from=build,source=/dist,target=/dist \
    apk upgrade --no-cache \
    && apk add --no-cache tini bash \
    && pip install --no-cache-dir --require-hashes -r /tmp/requirements-image.lock \
    && pip install --no-cache-dir --no-deps /dist/genesis_mesh-*.whl \
    && rm /tmp/requirements-image.lock \
    && python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.*/ensurepip/_bundled \
    && addgroup -S -g 10001 genesis \
    && adduser -S -D -H -u 10001 -G genesis -h /data -s /sbin/nologin genesis \
    && install -d -o 10001 -g 0 -m 2770 /data

COPY --chmod=755 start.sh /usr/local/bin/start.sh
COPY --chmod=755 docker/healthcheck.sh /usr/local/bin/healthcheck

USER 10001:10001
WORKDIR /data
EXPOSE 8443
# Health for Docker and Compose: the NA is healthy when /readyz answers; a
# mesh node has no HTTP endpoint, so its running process is its health.
# Kubernetes ignores HEALTHCHECK: use liveness and readiness probes there.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["/usr/local/bin/healthcheck"]
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/start.sh"]
