# The Network Authority from PyPI (GENESIS_MESH_VERSION), with the demo job's
# script available to the `demo` service. /data holds the SQLite store.
FROM python:3.14-slim
ARG GENESIS_MESH_VERSION
COPY dist/ /dist/
RUN set -e; \
    wheel=$(ls /dist/*.whl 2>/dev/null | head -n 1 || true); \
    if [ -n "$wheel" ]; then pip install --no-cache-dir "${wheel}"; \
    else test -n "$GENESIS_MESH_VERSION" && pip install --no-cache-dir "genesis-mesh==${GENESIS_MESH_VERSION}"; fi; \
    rm -rf /dist; \
    useradd --system --uid 10001 --home /nonexistent genesis; \
    install -d -o 10001 -g 10001 -m 700 /data /state /demo-data
USER genesis
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:8000 --workers ${WEB_CONCURRENCY:-2} --timeout 30 --access-logfile - --error-logfile - genesis_mesh.na_service.wsgi:app"]
