# The Network Authority as an operator installs it: the released package from
# PyPI (GENESIS_MESH_VERSION), or a release-candidate wheel placed in dist/.
FROM python:3.14-slim
ARG GENESIS_MESH_VERSION
COPY dist/ /dist/
RUN set -e; \
    wheel=$(ls /dist/*.whl 2>/dev/null | head -n 1 || true); \
    if [ -n "$wheel" ]; then pip install --no-cache-dir "${wheel}[postgres]"; \
    else test -n "$GENESIS_MESH_VERSION" && pip install --no-cache-dir "genesis-mesh[postgres]==${GENESIS_MESH_VERSION}"; fi; \
    rm -rf /dist; \
    useradd --system --uid 10001 --home /nonexistent genesis
USER genesis
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:8000 --workers ${WEB_CONCURRENCY:-2} --timeout 30 --access-logfile - --error-logfile - genesis_mesh.na_service.wsgi:app"]
