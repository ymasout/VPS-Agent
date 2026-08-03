ARG PYTHON_BASE_IMAGE=docker.io/library/python@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df
FROM ${PYTHON_BASE_IMAGE}
ARG CONTROL_PLANE_VERSION=unset
ARG CONTROL_PLANE_COMMIT_SHA=unknown-build
ARG CONTROL_PLANE_BUILD_TIME=unknown-build-time
ENV CONTROL_PLANE_VERSION=${CONTROL_PLANE_VERSION} \
    CONTROL_PLANE_COMMIT_SHA=${CONTROL_PLANE_COMMIT_SHA} \
    CONTROL_PLANE_BUILD_TIME=${CONTROL_PLANE_BUILD_TIME} \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
LABEL org.opencontainers.image.version=${CONTROL_PLANE_VERSION} \
      org.opencontainers.image.revision=${CONTROL_PLANE_COMMIT_SHA} \
      org.opencontainers.image.created=${CONTROL_PLANE_BUILD_TIME} \
      org.opencontainers.image.source=https://github.com/ymasout/VPS-Agent \
      org.opencontainers.image.licenses=AGPL-3.0-only
WORKDIR /app
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app
RUN addgroup -g 10001 vps-agent \
    && adduser -S -H -u 10001 -G vps-agent -h /nonexistent vps-agent
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
